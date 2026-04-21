"""Modular production-oriented multi-agent trading orchestrator."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from api.observability import log_structured
from api.services.agents.prompts import ADAPTIVE_TRADING_SYSTEM_PROMPT

try:
    import anthropic
except ImportError:  # pragma: no cover - dependency optional in tests
    anthropic = None

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


Direction = Literal["LONG", "SHORT", "FLAT"]


@dataclass
class AgentCall:
    agent_name: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    timestamp: datetime
    success: bool
    error: str | None = None
    duration_ms: int = 0


@dataclass
class PlanStep:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradePlan:
    asset: str
    timeframe: str
    steps: list[PlanStep]


class ToolError(RuntimeError):
    """Tool execution failed validation or guardrails."""


def _to_sync_db_url(raw_url: str) -> str:
    if raw_url.startswith("sqlite+aiosqlite://"):
        return raw_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    if raw_url.startswith("postgresql+asyncpg://"):
        return raw_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return raw_url


class MemoryGuard:
    def __init__(self, threshold: float = 0.82):
        self.threshold = threshold
        self.risk_memory_store: dict[str, int] = {}

    def check(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        db_url = _to_sync_db_url(os.getenv("DATABASE_URL", "sqlite:///./trading-control.db"))
        probe = f"{tool_name}:{json.dumps(payload, sort_keys=True)}"
        probe_embedding = self._embed(probe)
        try:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT content, embedding_json, metadata_json
                        FROM vector_memory_records
                        WHERE store_type = 'negative-memory'
                        ORDER BY id DESC
                        LIMIT 100
                        """)
                ).fetchall()
        except Exception:
            return None

        for row in rows:
            try:
                candidate = json.loads(row.embedding_json)
                similarity = self._cosine(probe_embedding, candidate)
                if similarity > self.threshold:
                    metadata = json.loads(row.metadata_json) if row.metadata_json else {}
                    risk_key = f"{tool_name}:{hashlib.sha256(probe.encode('utf-8')).hexdigest()}"
                    self.risk_memory_store[risk_key] = self.risk_memory_store.get(risk_key, 0) + 1
                    if self.risk_memory_store[risk_key] > 3:
                        return {
                            "similarity": 1.0,
                            "reason": "repeated_risk_violation",
                            "content": f"Pattern failed {self.risk_memory_store[risk_key]} times",
                        }
                    return {
                        "similarity": round(similarity, 3),
                        "reason": metadata.get("reason", "blocked by prior negative memory"),
                        "content": row.content,
                    }
            except Exception:
                continue
        return None

    def _embed(self, text_input: str) -> list[float]:
        digest = hashlib.sha256(text_input.encode("utf-8")).digest()
        return [round(b / 255.0, 6) for b in digest[:16]]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        a = a[:n]
        b = b[:n]
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class TradeConstraint(BaseModel):
    asset_ticker: str
    max_position_size: float = Field(default=5000, le=5000)
    order_type: Literal["limit", "market"] = "limit"
    stop_loss_pct: float = Field(default=0.02, ge=0.01)


class ReasoningModel(Protocol):
    def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicReasoningModel:
    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "claude-sonnet-4-20250514",
        retries: int = 2,
    ):
        if anthropic is None:
            raise RuntimeError("anthropic package is not installed")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_name = model_name
        self.retries = retries

    def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model_name,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": json.dumps(payload)}],
                )
                text = response.content[0].text
                return json.loads(text)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log_structured(
                    "warning",
                    "reasoning model retry",
                    attempt=attempt + 1,
                    exc_info=True,
                )
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"Model call failed after retries: {last_error}")


class DeterministicReasoningModel:
    """Fallback local model to keep flows deterministic in development/tests."""

    def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "normalize trade signals" in system_prompt.lower():
            direction: Direction = "LONG" if payload["asset"] in {"AAPL", "MSFT"} else "FLAT"
            return [
                {
                    "source": "heuristic",
                    "direction": direction,
                    "confidence": 0.7,
                    "timeframe": payload["timeframe"],
                }
            ]
        if "compute consensus" in system_prompt.lower():
            signals = payload.get("signals", [])
            if not signals:
                return {
                    "direction": "FLAT",
                    "agreement_ratio": 0.0,
                    "signal_strength": 0.0,
                }
            direction = signals[0]["direction"]
            agreement = sum(1 for s in signals if s["direction"] == direction) / len(signals)
            confidence = sum(float(s.get("confidence", 0)) for s in signals) / len(signals)
            return {
                "direction": direction,
                "agreement_ratio": agreement,
                "signal_strength": round(agreement * confidence, 3),
            }
        if "enforce risk limits" in system_prompt.lower():
            drawdown = float(payload.get("portfolio", {}).get("drawdown", 0))
            veto = drawdown < -0.15
            return {
                "approved": not veto,
                "veto": veto,
                "risk_score": min(1.0, abs(drawdown) * 2 + 0.1),
                "size_multiplier": 0.5 if veto else 1.0,
                "flags": ["MAX_DRAWDOWN"] if veto else [],
            }
        price = float(payload.get("asset_price", 100))
        atr = float(payload.get("atr", 5))
        return {
            "units": int(max(1, payload.get("portfolio_value", 100000) * 0.01 / max(price, 1))),
            "entry": price,
            "stop": max(0.01, price - atr),
            "target": price + atr * 2,
            "rr_ratio": 2.0,
        }


class DocumentRetriever:
    """Tiny local retriever for grounding outputs in checked-in references."""

    def __init__(self, root: str = "skills/trade-bot/references"):
        self.root = Path(root)
        self.documents: dict[str, str] = {}
        if self.root.exists():
            for path in self.root.glob("*.md"):
                self.documents[path.name] = path.read_text(encoding="utf-8")

    def retrieve(self, query: str, *, top_k: int = 2) -> list[dict[str, str]]:
        scored: list[tuple[int, str, str]] = []
        q_terms = {term.lower() for term in query.split() if len(term) > 2}
        for name, doc_text in self.documents.items():
            lower = doc_text.lower()
            score = sum(1 for term in q_terms if term in lower)
            if score:
                scored.append((score, name, doc_text[:500]))
        scored.sort(reverse=True)
        return [{"source": name, "snippet": snippet} for _, name, snippet in scored[:top_k]]


class TradeTools:
    def __init__(
        self,
        *,
        allowed_assets: set[str] | None = None,
        price_provider: Callable[[str], float] | None = None,
        max_retries: int = 2,
        circuit_breaker_threshold: int = 3,
    ):
        self.allowed_assets = allowed_assets or {"AAPL", "MSFT", "GOOGL", "TSLA"}
        self.price_provider = price_provider or (
            lambda asset: {
                "AAPL": 150.25,
                "MSFT": 380.5,
                "GOOGL": 2800.0,
                "TSLA": 250.0,
            }[asset]
        )
        self.max_retries = max_retries
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.failure_count = 0
        self.circuit_open = False
        self.memory_guard = MemoryGuard()
        self.guard_hits = 0

    def _guard(self, tool_name: str, payload: dict[str, Any]) -> None:
        match = self.memory_guard.check(tool_name, payload)
        if not match:
            return
        self.guard_hits += 1
        reason = match.get("reason", "blocked")
        raise ToolError(f"skipped_by_memory_guard:{reason}")

    def get_current_price(self, asset: str) -> float:
        self._guard("get_current_price", {"asset": asset})
        if self.circuit_open:
            raise ToolError("Price tool circuit breaker is open")
        if asset not in self.allowed_assets:
            raise ToolError(f"Asset '{asset}' blocked by tool guardrail")
        for _ in range(self.max_retries + 1):
            try:
                price = float(self.price_provider(asset))
                self.failure_count = 0
                return price
            except Exception as exc:  # noqa: BLE001
                self.failure_count += 1
                if self.failure_count >= self.circuit_breaker_threshold:
                    self.circuit_open = True
                last_error = exc
        raise ToolError(f"Price lookup failed after retries: {last_error}")

    def get_atr(self, asset: str, timeframe: str) -> float:
        self._guard("get_atr", {"asset": asset, "timeframe": timeframe})
        if timeframe not in {"1H", "4H", "1D", "1W"}:
            raise ToolError(f"Unsupported timeframe '{timeframe}'")
        _ = asset
        return 5.0


class ConversationMemory:
    def __init__(self, limit: int = 10):
        self.limit = limit
        self.events: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.events = self.events[-self.limit :]


class TaskStateMemory:
    def __init__(self):
        self.state: dict[str, dict[str, Any]] = {}

    def put(self, task_id: str, value: dict[str, Any]) -> None:
        self.state[task_id] = value

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.state.get(task_id)


class PersistentMemory:
    def __init__(self, path: str = "trade-memory.json"):
        self.path = Path(path)
        self._store = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"trades": []}

    def append_trade(self, trade: dict[str, Any]) -> None:
        self._store.setdefault("trades", []).append(trade)
        self.path.write_text(json.dumps(self._store, indent=2, default=str), encoding="utf-8")


class Planner:
    def build_plan(self, asset: str, timeframe: str) -> TradePlan:
        return TradePlan(
            asset=asset,
            timeframe=timeframe,
            steps=[
                PlanStep("signal"),
                PlanStep("consensus"),
                PlanStep("risk"),
                PlanStep("sizing"),
                PlanStep("decision"),
            ],
        )


class ExecutionEngine:
    AGENT_PROMPTS: dict[str, str] = {
        "SIGNAL_AGENT": ADAPTIVE_TRADING_SYSTEM_PROMPT,
        "CONSENSUS_AGENT": "You aggregate signals with IC-weighted consensus. Return JSON object only.",
        "RISK_AGENT": "You enforce capital preservation first and can veto trades. Return JSON object only.",
        "SIZING_AGENT": "You calculate Kelly-based position sizing with risk multipliers. Return JSON object only.",
    }

    def __init__(self, model: ReasoningModel, retriever: DocumentRetriever, tools: TradeTools):
        self.model = model
        self.retriever = retriever
        self.tools = tools

    def run_step(self, step: PlanStep, context: dict[str, Any]) -> dict[str, Any]:
        if step.name == "signal":
            grounding = self.retriever.retrieve(f"{context['asset']} {context['timeframe']} signal")
            payload = {
                "asset": context["asset"],
                "timeframe": context["timeframe"],
                "grounding": grounding,
            }
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["SIGNAL_AGENT"], payload=payload
            )
        if step.name == "consensus":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["CONSENSUS_AGENT"],
                payload={"signals": context["signals"]},
            )
        if step.name == "risk":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["RISK_AGENT"],
                payload={
                    "consensus": context["consensus"],
                    "portfolio": context["portfolio_state"],
                },
            )
        if step.name == "sizing":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["SIZING_AGENT"],
                payload={
                    "consensus": context["consensus"],
                    "risk": context["risk"],
                    "asset_price": self.tools.get_current_price(context["asset"]),
                    "atr": self.tools.get_atr(context["asset"], context["timeframe"]),
                    "portfolio_value": context["portfolio_state"].get("total_value", 100000),
                },
            )
        if step.name == "decision":
            return self._format_decision(context)
        raise ValueError(f"Unknown plan step {step.name}")

    def _format_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        consensus = context["consensus"]
        risk = context["risk"]
        sizing = context["sizing"]
        signal_strength = float(consensus.get("signal_strength", 0))
        confidence = (
            "HIGH" if signal_strength > 0.8 else "MEDIUM" if signal_strength > 0.6 else "LOW"
        )
        return {
            "DECISION": consensus.get("direction", "FLAT"),
            "ASSET": context["asset"],
            "SIZE": f"{sizing.get('units', 0)} units",
            "ENTRY": f"{float(sizing.get('entry', 0)):.2f}",
            "STOP": f"{float(sizing.get('stop', 0)):.2f}",
            "TARGET": f"{float(sizing.get('target', 0)):.2f}",
            "R/R RATIO": f"{float(sizing.get('rr_ratio', 0)):.1f}:1",
            "CONFIDENCE": confidence,
            "SIGNAL SUMMARY": [
                f"Consensus={consensus.get('agreement_ratio', 0):.1%}",
                f"Risk veto={risk.get('veto', False)}",
            ],
            "RISK FLAGS": risk.get("flags", []),
            "RATIONALE": "Grounded decision via planner/executor pipeline.",
            "INVALIDATION": f"Below stop {float(sizing.get('stop', 0)):.2f}",
            "TRACE SUMMARY": {"guard_hits": self.tools.guard_hits},
        }


class EvaluationLayer:
    def validate_trajectory(self, trace: list[AgentCall]) -> list[str]:
        issues = []
        if not trace:
            issues.append("empty_trace")
        if any(not call.success for call in trace):
            issues.append("step_failure")
        return issues

    def validate_outcome(self, decision: dict[str, Any]) -> list[str]:
        required = {"DECISION", "ASSET", "SIZE", "CONFIDENCE"}
        missing = sorted(required - set(decision))
        return [f"missing:{k}" for k in missing]


class MultiAgentOrchestrator:
    """Production-grade orchestrator with planner/executor/memory/eval layers."""

    def __init__(self, api_key: str | None = None):
        model: ReasoningModel
        if api_key:
            model = AnthropicReasoningModel(api_key)
        else:
            model = DeterministicReasoningModel()
        self.planner = Planner()
        self.executor = ExecutionEngine(model, DocumentRetriever(), TradeTools())
        self.conversation_memory = ConversationMemory(limit=20)
        self.task_memory = TaskStateMemory()
        self.persistent_memory = PersistentMemory()
        self.evaluator = EvaluationLayer()
        self.agent_calls: list[AgentCall] = []
        self.trade_log: list[dict[str, Any]] = []

    def call_agent(self, agent_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Compatibility interface for legacy callers."""
        prompt_key = f"{agent_name}"
        step_map = {
            "SIGNAL_AGENT": "signal",
            "CONSENSUS_AGENT": "consensus",
            "RISK_AGENT": "risk",
            "SIZING_AGENT": "sizing",
        }
        step_name = step_map.get(prompt_key)
        if not step_name:
            return {"success": False, "error": "Unknown agent"}

        start = time.time()
        try:
            output = self.executor.run_step(PlanStep(step_name), input_data)
            call = AgentCall(
                agent_name,
                input_data,
                output,
                datetime.now(timezone.utc),
                True,
                duration_ms=int((time.time() - start) * 1000),
            )
            self.agent_calls.append(call)
            return {"success": True, "data": output}
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            call = AgentCall(
                agent_name,
                input_data,
                {},
                datetime.now(timezone.utc),
                False,
                error=error_text,
                duration_ms=int((time.time() - start) * 1000),
            )
            self.agent_calls.append(call)
            return {"success": False, "error": str(exc)}

    def analyze_trade(
        self,
        asset: str,
        timeframe: str,
        portfolio_state: dict[str, Any],
        *,
        max_iterations: int = 2,
    ) -> dict[str, Any]:
        """Run an explicit agentic loop: perceive → think/plan → act → evaluate → repeat."""
        self.agent_calls = []
        current_timeframe = timeframe
        final_decision: dict[str, Any] | None = None
        final_trajectory_issues: list[str] = []
        final_outcome_issues: list[str] = []

        for iteration in range(1, max_iterations + 1):
            decision, trajectory_issues, outcome_issues = self._analyze_trade_once(
                asset, current_timeframe, portfolio_state
            )
            decision["LOOP_ITERATION"] = iteration
            final_decision = decision
            final_trajectory_issues = trajectory_issues
            final_outcome_issues = outcome_issues
            if not self._should_retry(
                decision, trajectory_issues, outcome_issues, iteration, max_iterations
            ):
                break
            current_timeframe = self._next_timeframe(current_timeframe)
            self.conversation_memory.add(
                {
                    "loop_event": "retry",
                    "iteration": iteration,
                    "next_timeframe": current_timeframe,
                    "reason": "low_confidence_or_validation_issues",
                }
            )

        if final_decision is None:
            return self._error_decision(asset, "orchestrator produced no decision")

        if final_trajectory_issues or final_outcome_issues:
            final_decision.setdefault("RISK FLAGS", []).extend(
                final_trajectory_issues + final_outcome_issues
            )
        final_decision["LOOP_COMPLETED"] = True
        final_decision["LOOP_MAX_ITERATIONS"] = max_iterations
        return final_decision

    def _analyze_trade_once(
        self, asset: str, timeframe: str, portfolio_state: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        task_id = f"{asset}:{datetime.now(timezone.utc).isoformat()}"
        plan = self.planner.build_plan(asset, timeframe)
        context: dict[str, Any] = {
            "asset": asset,
            "timeframe": timeframe,
            "portfolio_state": portfolio_state,
        }

        for step in plan.steps:
            step_start = time.time()
            try:
                if step.name == "signal":
                    context["signals"] = self.executor.run_step(step, context)
                elif step.name == "consensus":
                    context["consensus"] = self.executor.run_step(step, context)
                    if float(context["consensus"].get("agreement_ratio", 0.0)) < 0.5:
                        context["risk"] = {"veto": True, "flags": ["LOW_CONSENSUS"]}
                        context["sizing"] = {
                            "units": 0,
                            "entry": 0,
                            "stop": 0,
                            "target": 0,
                            "rr_ratio": 0,
                        }
                        break
                elif step.name == "risk":
                    context["risk"] = self.executor.run_step(step, context)
                    if bool(context["risk"].get("veto", False)):
                        context["sizing"] = {
                            "units": 0,
                            "entry": 0,
                            "stop": 0,
                            "target": 0,
                            "rr_ratio": 0,
                        }
                        break
                elif step.name == "sizing":
                    context["sizing"] = self.executor.run_step(step, context)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                agent_name = (
                    "skipped_by_memory_guard"
                    if "skipped_by_memory_guard" in error_text
                    else step.name.upper()
                )
                self.agent_calls.append(
                    AgentCall(
                        agent_name,
                        context.copy(),
                        {},
                        datetime.now(timezone.utc),
                        False,
                        error=error_text,
                        duration_ms=int((time.time() - step_start) * 1000),
                    )
                )
                decision = self._error_decision(asset, error_text)
                decision["context_dump"] = {
                    "task_state": self.task_memory.get(task_id),
                    "retrieved_context": context.get("signals", []),
                }
                self._persist(task_id, decision)
                return decision, ["step_failure"], []

            self.agent_calls.append(
                AgentCall(
                    step.name.upper(),
                    context.copy(),
                    context.get(step.name, {}),
                    datetime.now(timezone.utc),
                    True,
                    duration_ms=int((time.time() - step_start) * 1000),
                )
            )
            self.task_memory.put(task_id, {"last_step": step.name, "context": context.copy()})

        decision = self.executor.run_step(PlanStep("decision"), context)
        trajectory_issues = self.evaluator.validate_trajectory(self.agent_calls)
        outcome_issues = self.evaluator.validate_outcome(decision)
        self._persist(task_id, decision)
        return decision, trajectory_issues, outcome_issues

    def _should_retry(
        self,
        decision: dict[str, Any],
        trajectory_issues: list[str],
        outcome_issues: list[str],
        iteration: int,
        max_iterations: int,
    ) -> bool:
        if iteration >= max_iterations:
            return False
        if "SYSTEM_ERROR" in decision.get("RISK FLAGS", []):
            return False
        if trajectory_issues or outcome_issues:
            return True
        if decision.get("CONFIDENCE") == "LOW":
            return True
        return "LOW_CONSENSUS" in decision.get("RISK FLAGS", [])

    def _next_timeframe(self, timeframe: str) -> str:
        fallback_order = {"1W": "1D", "1D": "4H", "4H": "1H", "1H": "1D"}
        return fallback_order.get(timeframe, "1D")

    def process_trade_signals(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        symbol = signals[0].get("symbol", "AAPL") if signals else "AAPL"
        price = float(signals[0].get("price", 100)) if signals else 100
        portfolio = {
            "total_value": 100000,
            "cash": 50000,
            "positions": {},
            "drawdown": -0.03,
            "price_hint": price,
        }
        decision = self.analyze_trade(symbol, "1D", portfolio)
        return {
            "DECISION": decision["DECISION"],
            "confidence": 0.8 if decision["CONFIDENCE"] == "HIGH" else 0.6,
            "reasoning": decision["RATIONALE"],
            "position_size": 0.02,
            "risk_assessment": {"flags": decision.get("RISK FLAGS", [])},
        }

    def _error_decision(self, asset: str, message: str) -> dict[str, Any]:
        return {
            "DECISION": "FLAT",
            "ASSET": asset,
            "SIZE": "0 units",
            "ENTRY": "0.00",
            "STOP": "0.00",
            "TARGET": "0.00",
            "R/R RATIO": "0.0:1",
            "CONFIDENCE": "LOW",
            "SIGNAL SUMMARY": [f"error={message}"],
            "RISK FLAGS": ["SYSTEM_ERROR"],
            "RATIONALE": "Execution failed",
            "INVALIDATION": "N/A",
        }

    def _persist(self, task_id: str, decision: dict[str, Any]) -> None:
        log_entry = {
            "trace_summary": {"guard_hits": self.executor.tools.guard_hits},
            "task_id": task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "trace": [asdict(call) for call in self.agent_calls],
        }
        self.conversation_memory.add(log_entry)
        self.trade_log.append(log_entry)
        self.persistent_memory.append_trade(log_entry)
        Path("trade-log.json").write_text(
            json.dumps(self.trade_log, indent=2, default=str), encoding="utf-8"
        )

    def get_trade_history(self) -> list[dict[str, Any]]:
        return self.trade_log

    def get_performance_stats(self) -> dict[str, Any]:
        decisions = [entry["decision"]["DECISION"] for entry in self.trade_log]
        total = len(decisions)
        if total == 0:
            return {"total_trades": 0}
        return {
            "total_trades": total,
            "long_trades": decisions.count("LONG"),
            "short_trades": decisions.count("SHORT"),
            "flat_trades": decisions.count("FLAT"),
            "trade_rate": (decisions.count("LONG") + decisions.count("SHORT")) / total,
        }


if __name__ == "__main__":
    orchestrator = MultiAgentOrchestrator(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = orchestrator.analyze_trade("AAPL", "1D", {"total_value": 100000, "drawdown": -0.02})
    log_structured("info", "trade analysis result", result=result)
