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

from api.constants import FieldName
from api.observability import log_structured
from api.services.agents.prompts import ADAPTIVE_TRADING_SYSTEM_PROMPT
from api.utils import get_nested

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
                            FieldName.SIMILARITY: 1.0,
                            "reason": "repeated_risk_violation",
                            "content": f"Pattern failed {self.risk_memory_store[risk_key]} times",
                        }
                    return {
                        FieldName.SIMILARITY: round(similarity, 3),
                        "reason": metadata.get(
                            FieldName.REASON, "blocked by prior negative memory"
                        ),
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
                    messages=[{FieldName.ROLE: "user", "content": json.dumps(payload)}],
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
            direction: Direction = (
                "LONG" if payload[FieldName.ASSET] in {"AAPL", "MSFT"} else "FLAT"
            )
            return [
                {
                    "source": "heuristic",
                    "direction": direction,
                    "confidence": 0.7,
                    FieldName.TIMEFRAME: payload[FieldName.TIMEFRAME],
                }
            ]
        if "compute consensus" in system_prompt.lower():
            signals = payload.get(FieldName.SIGNALS, [])
            if not signals:
                return {
                    "direction": "FLAT",
                    FieldName.AGREEMENT_RATIO: 0.0,
                    FieldName.SIGNAL_STRENGTH: 0.0,
                }
            direction = signals[0][FieldName.DIRECTION]
            agreement = sum(1 for s in signals if s[FieldName.DIRECTION] == direction) / len(
                signals
            )
            confidence = sum(float(s.get(FieldName.CONFIDENCE, 0)) for s in signals) / len(signals)
            return {
                "direction": direction,
                FieldName.AGREEMENT_RATIO: agreement,
                FieldName.SIGNAL_STRENGTH: round(agreement * confidence, 3),
            }
        if "enforce risk limits" in system_prompt.lower():
            drawdown = float(get_nested(payload, "portfolio", "drawdown", default=0))
            veto = drawdown < -0.15
            return {
                FieldName.APPROVED: not veto,
                FieldName.VETO: veto,
                FieldName.RISK_SCORE: min(1.0, abs(drawdown) * 2 + 0.1),
                FieldName.SIZE_MULTIPLIER: 0.5 if veto else 1.0,
                FieldName.FLAGS: ["MAX_DRAWDOWN"] if veto else [],
            }
        price = float(payload.get(FieldName.ASSET_PRICE, 100))
        atr = float(payload.get(FieldName.ATR, 5))
        return {
            FieldName.UNITS: int(
                max(1, payload.get(FieldName.PORTFOLIO_VALUE, 100000) * 0.01 / max(price, 1))
            ),
            FieldName.ENTRY: price,
            FieldName.STOP: max(0.01, price - atr),
            FieldName.TARGET: price + atr * 2,
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
        return [{"source": name, FieldName.SNIPPET: snippet} for _, name, snippet in scored[:top_k]]


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
        reason = match.get(FieldName.REASON, "blocked")
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
        self._guard("get_atr", {"asset": asset, FieldName.TIMEFRAME: timeframe})
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
        return {FieldName.TRADES: []}

    def append_trade(self, trade: dict[str, Any]) -> None:
        self._store.setdefault(FieldName.TRADES, []).append(trade)
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
            grounding = self.retriever.retrieve(
                f"{context[FieldName.ASSET]} {context[FieldName.TIMEFRAME]} signal"
            )
            payload = {
                "asset": context[FieldName.ASSET],
                FieldName.TIMEFRAME: context[FieldName.TIMEFRAME],
                FieldName.GROUNDING: grounding,
            }
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["SIGNAL_AGENT"], payload=payload
            )
        if step.name == "consensus":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["CONSENSUS_AGENT"],
                payload={FieldName.SIGNALS: context[FieldName.SIGNALS]},
            )
        if step.name == "risk":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["RISK_AGENT"],
                payload={
                    FieldName.CONSENSUS: context[FieldName.CONSENSUS],
                    FieldName.PORTFOLIO: context[FieldName.PORTFOLIO_STATE],
                },
            )
        if step.name == "sizing":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["SIZING_AGENT"],
                payload={
                    FieldName.CONSENSUS: context[FieldName.CONSENSUS],
                    FieldName.RISK: context[FieldName.RISK],
                    FieldName.ASSET_PRICE: self.tools.get_current_price(context[FieldName.ASSET]),
                    FieldName.ATR: self.tools.get_atr(
                        context[FieldName.ASSET], context[FieldName.TIMEFRAME]
                    ),
                    FieldName.PORTFOLIO_VALUE: context[FieldName.PORTFOLIO_STATE].get(
                        FieldName.TOTAL_VALUE, 100000
                    ),
                },
            )
        if step.name == "decision":
            return self._format_decision(context)
        raise ValueError(f"Unknown plan step {step.name}")

    def _format_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        consensus = context[FieldName.CONSENSUS]
        risk = context[FieldName.RISK]
        sizing = context[FieldName.SIZING]
        signal_strength = float(consensus.get(FieldName.SIGNAL_STRENGTH, 0))
        confidence = (
            "HIGH" if signal_strength > 0.8 else "MEDIUM" if signal_strength > 0.6 else "LOW"
        )
        return {
            "DECISION": consensus.get(FieldName.DIRECTION, "FLAT"),
            "ASSET": context[FieldName.ASSET],
            "SIZE": f"{sizing.get(FieldName.UNITS, 0)} units",
            "ENTRY": f"{float(sizing.get(FieldName.ENTRY, 0)):.2f}",
            "STOP": f"{float(sizing.get(FieldName.STOP, 0)):.2f}",
            "TARGET": f"{float(sizing.get(FieldName.TARGET, 0)):.2f}",
            "R/R RATIO": f"{float(sizing.get(FieldName.RR_RATIO, 0)):.1f}:1",
            "CONFIDENCE": confidence,
            "SIGNAL SUMMARY": [
                f"Consensus={consensus.get(FieldName.AGREEMENT_RATIO, 0):.1%}",
                f"Risk veto={risk.get(FieldName.VETO, False)}",
            ],
            "RISK FLAGS": risk.get(FieldName.FLAGS, []),
            "RATIONALE": "Grounded decision via planner/executor pipeline.",
            "INVALIDATION": f"Below stop {float(sizing.get(FieldName.STOP, 0)):.2f}",
            "TRACE SUMMARY": {FieldName.GUARD_HITS: self.tools.guard_hits},
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
            return {FieldName.SUCCESS: False, "error": "Unknown agent"}

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
            return {FieldName.SUCCESS: True, "data": output}
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
            return {FieldName.SUCCESS: False, "error": str(exc)}

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
                    FieldName.LOOP_EVENT: "retry",
                    FieldName.ITERATION: iteration,
                    FieldName.NEXT_TIMEFRAME: current_timeframe,
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
            FieldName.TIMEFRAME: timeframe,
            FieldName.PORTFOLIO_STATE: portfolio_state,
        }

        for step in plan.steps:
            step_start = time.time()
            try:
                if step.name == "signal":
                    context[FieldName.SIGNALS] = self.executor.run_step(step, context)
                elif step.name == "consensus":
                    context[FieldName.CONSENSUS] = self.executor.run_step(step, context)
                    if (
                        float(context[FieldName.CONSENSUS].get(FieldName.AGREEMENT_RATIO, 0.0))
                        < 0.5
                    ):
                        context[FieldName.RISK] = {
                            FieldName.VETO: True,
                            FieldName.FLAGS: ["LOW_CONSENSUS"],
                        }
                        context[FieldName.SIZING] = {
                            FieldName.UNITS: 0,
                            FieldName.ENTRY: 0,
                            FieldName.STOP: 0,
                            FieldName.TARGET: 0,
                            "rr_ratio": 0,
                        }
                        break
                elif step.name == "risk":
                    context[FieldName.RISK] = self.executor.run_step(step, context)
                    if bool(context[FieldName.RISK].get(FieldName.VETO, False)):
                        context[FieldName.SIZING] = {
                            FieldName.UNITS: 0,
                            FieldName.ENTRY: 0,
                            FieldName.STOP: 0,
                            FieldName.TARGET: 0,
                            "rr_ratio": 0,
                        }
                        break
                elif step.name == "sizing":
                    context[FieldName.SIZING] = self.executor.run_step(step, context)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                agent_name = (
                    "skipped_by_memory_guard"
                    if FieldName.SKIPPED_BY_MEMORY_GUARD in error_text
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
                decision[FieldName.CONTEXT_DUMP] = {
                    FieldName.TASK_STATE: self.task_memory.get(task_id),
                    FieldName.RETRIEVED_CONTEXT: context.get(FieldName.SIGNALS, []),
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
            self.task_memory.put(
                task_id, {FieldName.LAST_STEP: step.name, FieldName.CONTEXT: context.copy()}
            )

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
        symbol = signals[0].get(FieldName.SYMBOL, "AAPL") if signals else "AAPL"
        price = float(signals[0].get(FieldName.PRICE, 100)) if signals else 100
        portfolio = {
            FieldName.TOTAL_VALUE: 100000,
            FieldName.CASH: 50000,
            FieldName.POSITIONS: {},
            FieldName.DRAWDOWN: -0.03,
            FieldName.PRICE_HINT: price,
        }
        decision = self.analyze_trade(symbol, "1D", portfolio)
        return {
            "DECISION": decision["DECISION"],
            "confidence": 0.8 if decision["CONFIDENCE"] == "HIGH" else 0.6,
            FieldName.REASONING: decision["RATIONALE"],
            FieldName.POSITION_SIZE: 0.02,
            FieldName.RISK_ASSESSMENT: {FieldName.FLAGS: decision.get("RISK FLAGS", [])},
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
            FieldName.TRACE_SUMMARY: {FieldName.GUARD_HITS: self.executor.tools.guard_hits},
            FieldName.TASK_ID: task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            FieldName.DECISION: decision,
            FieldName.TRACE: [asdict(call) for call in self.agent_calls],
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
        decisions = [entry[FieldName.DECISION]["DECISION"] for entry in self.trade_log]
        total = len(decisions)
        if total == 0:
            return {FieldName.TOTAL_TRADES: 0}
        return {
            FieldName.TOTAL_TRADES: total,
            FieldName.LONG_TRADES: decisions.count("LONG"),
            FieldName.SHORT_TRADES: decisions.count("SHORT"),
            FieldName.FLAT_TRADES: decisions.count("FLAT"),
            FieldName.TRADE_RATE: (decisions.count("LONG") + decisions.count("SHORT")) / total,
        }


if __name__ == "__main__":
    orchestrator = MultiAgentOrchestrator(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = orchestrator.analyze_trade(
        "AAPL", "1D", {FieldName.TOTAL_VALUE: 100000, FieldName.DRAWDOWN: -0.02}
    )
    log_structured("info", "trade analysis result", result=result)
