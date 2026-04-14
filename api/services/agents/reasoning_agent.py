"""Reasoning agent: makes trading decisions using LLM analysis of signals.

DB routing:
  - is_db_available() is checked upfront in process().
  - DB mode: writes to agent_runs, cost_tracking, vector_memory via a real session.
  - Memory mode: stores everything in InMemoryStore, no DB session opened at all.
  - get_persistence_mode() is NOT used here; it always returned "auto" and was dead code.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_REASONING,
    LLM_FALLBACK_MODE_REJECT_SIGNAL,
    LLM_FALLBACK_MODE_USE_LAST_REFLECTION,
    NO_ORDER_ACTIONS,
    REACT_CRITIQUE_CONFIDENCE_THRESHOLD,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_LLM_COST,
    REDIS_KEY_LLM_TOKENS,
    SOURCE_REASONING,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
    AgentAction,
)
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agents.db_helpers import get_last_reflection, write_agent_log
from api.services.agents.prompts import REASONING_CRITIQUE_PROMPT
from api.services.agents.vector_helpers import (
    build_vector_literal,
    embed_text,
    search_vector_memory,
)
from api.services.llm_router import call_llm, call_llm_with_system


class ReasoningAgent(BaseStreamConsumer):
    """Listens on the ``signals`` stream and publishes advisory decisions to ``decisions``.

    This agent is a validator, not a decider. It outputs reasoning_score + recommended action
    to STREAM_DECISIONS. The ExecutionEngine is the sole authority for BUY/SELL orders.
    """

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client):
        super().__init__(
            bus, dlq, stream=STREAM_SIGNALS, group=DEFAULT_GROUP, consumer="reasoning-agent"
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        today = date.today().isoformat()
        trace_id = str(uuid.uuid4())

        budget_used = int(await self.redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)

        # ReAct Step 1: Gather context (IC weights + risk state) before reasoning
        context = await self._gather_context(data)

        signal_summary = self._build_signal_summary(data)
        embedding = await embed_text(signal_summary)

        try:
            similar_trades = await search_vector_memory(embedding)
        except Exception:
            log_structured("warning", "vector_memory_search_failed", exc_info=True)
            similar_trades = []

        # --- LLM decision (enriched with gathered context) ---------------
        fallback_reason: str | None = None
        if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            fallback_reason = "budget_exceeded"
            summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
            tokens_used, cost_usd = 0, 0.0
        else:
            try:
                summary, tokens_used, cost_usd = await self._call_llm(
                    data, similar_trades, trace_id, context
                )
            except Exception as exc:  # noqa: BLE001
                fallback_reason = str(exc)
                summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
                tokens_used, cost_usd = 0, 0.0

        is_fallback = fallback_reason is not None

        # ReAct Step 2: Self-critique for high-confidence actionable decisions
        # Only runs when: not a fallback, action is buy/sell, confidence is high enough
        action = str(summary.get("action", "")).lower()
        confidence = float(summary.get("confidence") or 0.0)
        if (
            not is_fallback
            and action not in NO_ORDER_ACTIONS
            and confidence >= REACT_CRITIQUE_CONFIDENCE_THRESHOLD
        ):
            critique_summary, critique_tokens, critique_cost = await self._self_critique(
                summary, context, trace_id
            )
            summary = critique_summary
            tokens_used += critique_tokens
            cost_usd += critique_cost

        # --- Persist agent run + cost tracking ---------------------------
        agent_run_id = await self._persist_run(
            data, summary, trace_id, is_fallback, today, tokens_used, cost_usd
        )

        # --- Agent log ---------------------------------------------------
        await write_agent_log(
            trace_id,
            "reasoning_summary",
            {**summary, "fallback_reason": fallback_reason, "source": SOURCE_REASONING},
            agent_run_id=agent_run_id,
        )

        # --- Vector memory (best-effort) ---------------------------------
        await self._persist_vector(signal_summary, embedding, summary)

        log_structured(
            "info", "reasoning_decision", trace_id=trace_id, action=summary.get("action")
        )

        # --- Heartbeat ---------------------------------------------------
        await _write_heartbeat(
            self.redis,
            AGENT_REASONING,
            f"action={summary.get('action')} symbol={data.get('symbol')}",
        )

        # --- Redis cost tracking -----------------------------------------
        await self.redis.incrby(REDIS_KEY_LLM_TOKENS.format(date=today), tokens_used)
        await self.redis.incrbyfloat(REDIS_KEY_LLM_COST.format(date=today), cost_usd)

        try:
            current_cost = float(await self.redis.get(REDIS_KEY_LLM_COST.format(date=today)) or 0.0)
            await self.bus.publish(
                STREAM_SYSTEM_METRICS,
                {
                    "type": "system_metric",
                    "metric_name": "llm_cost_today",
                    "value": current_cost,
                    "source": SOURCE_REASONING,
                },
            )
        except Exception:
            pass  # Cost metric is informational only

        updated_budget = int(await self.redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
        if updated_budget >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            await self.bus.publish(
                STREAM_RISK_ALERTS,
                {
                    "type": "llm_budget",
                    "message": "Daily LLM token budget exceeded",
                    "tokens_used": updated_budget,
                    "limit": settings.ANTHROPIC_DAILY_TOKEN_BUDGET,
                },
            )

        await self.bus.publish(
            STREAM_AGENT_LOGS,
            {
                "type": "agent_log",
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_REASONING,
                **summary,
            },
        )

        # --- Publish advisory decision to STREAM_DECISIONS ------------------
        # ReasoningAgent is advisory only — ExecutionEngine makes the final call.
        # Always publish regardless of action so ExecutionEngine can compute the
        # weighted score (signal_confidence * 0.50 + reasoning_score * 0.30 + perf * 0.20).
        action = summary.get("action", "").lower()
        strategy_id = str(data.get("strategy_id") or uuid.uuid4())
        await self.bus.publish(
            STREAM_DECISIONS,
            {
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_REASONING,
                "strategy_id": strategy_id,
                "signal_id": str(data.get("signal_id") or data.get("msg_id") or ""),
                "symbol": data.get("symbol"),
                "action": action,
                # Advisory scores — ExecutionEngine uses these in weighted formula
                "reasoning_score": float(summary.get("confidence") or 0.0),
                "signal_confidence": float(
                    data.get("composite_score") or data.get("confidence") or 0.0
                ),
                # Order parameters forwarded for ExecutionEngine use
                "qty": max(float(data.get("qty", 1.0)), float(summary.get("size_pct", 1.0))),
                "price": float(data.get("price", data.get("last_price", 0.0))),
                "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "trace_id": trace_id,
                "primary_edge": summary.get("primary_edge", ""),
                "risk_factors": summary.get("risk_factors", []),
                "size_pct": float(summary.get("size_pct") or 0.01),
                "stop_atr_x": float(summary.get("stop_atr_x") or 1.5),
                "rr_ratio": float(summary.get("rr_ratio") or 2.0),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_signal_summary(self, data: dict[str, Any]) -> str:
        return json.dumps(
            {
                "symbol": data.get("symbol"),
                "price": data.get("price"),
                "composite_score": data.get("composite_score"),
                # Signal publishes "type" (e.g. "STRONG_MOMENTUM"); some callers use "signal_type"
                "signal_type": data.get("signal_type") or data.get("type"),
                "context": data.get("context", {}),
            },
            sort_keys=True,
            default=str,
        )

    async def _gather_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """ReAct context gathering: fetch IC weights and derive risk state from signal.

        This is the 'Observe' step — the agent collects environmental state before
        deciding, rather than reasoning in a vacuum.
        """
        context: dict[str, Any] = {}

        # Fetch live IC factor weights from Redis (written by ICUpdater)
        try:
            ic_raw = await self.redis.get(REDIS_KEY_IC_WEIGHTS)
            if ic_raw:
                context["ic_weights"] = json.loads(ic_raw)
        except Exception:
            log_structured("warning", "reasoning_ic_weights_fetch_failed", exc_info=True)

        # Derive risk state from the signal itself
        context["risk_state"] = {
            "composite_score": float(data.get("composite_score") or 0.0),
            "momentum_pct": float(data.get("pct") or 0.0),
            "signal_strength": data.get("strength", "NORMAL"),
            "signal_type": data.get("type") or data.get("signal_type", "UNKNOWN"),
        }

        log_structured(
            "info",
            "reasoning_context_gathered",
            has_ic_weights=bool(context.get("ic_weights")),
            signal_type=context["risk_state"]["signal_type"],
        )
        return context

    async def _self_critique(
        self,
        decision: dict[str, Any],
        context: dict[str, Any],
        trace_id: str,
    ) -> tuple[dict[str, Any], int, float]:
        """ReAct self-critique: the agent evaluates its own decision before acting.

        If the critique finds the decision unjustified, it applies the recommended
        action and confidence. Falls back to the original decision on any error.
        Returns (decision, tokens_used, cost_usd).
        """
        try:
            critique_prompt = json.dumps(
                {
                    "decision": decision,
                    "ic_weights": context.get("ic_weights", {}),
                    "risk_state": context.get("risk_state", {}),
                },
                default=str,
            )
            raw_text, tokens, cost = await call_llm_with_system(
                critique_prompt, REASONING_CRITIQUE_PROMPT, trace_id
            )
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
                if "\n" in cleaned:
                    first, rest = cleaned.split("\n", 1)
                    if first.strip() in {"json", "JSON", ""}:
                        cleaned = rest
                if cleaned.rstrip().endswith("```"):
                    cleaned = cleaned.rstrip()[:-3].strip()
            critique = json.loads(cleaned)

            log_structured(
                "info",
                "reasoning_self_critique_completed",
                trace_id=trace_id,
                justified=critique.get("justified"),
                concerns=critique.get("concerns", []),
                original_action=decision.get("action"),
                recommended_action=critique.get("recommended_action"),
            )

            # Apply critique only when it explicitly flags the decision as unjustified
            if not critique.get("justified", True):
                rec_action = str(critique.get("recommended_action") or decision["action"]).lower()
                rec_confidence = float(
                    critique.get("recommended_confidence") or decision["confidence"]
                )
                refined = {
                    **decision,
                    "action": rec_action,
                    "confidence": round(rec_confidence, 4),
                    "risk_factors": list(decision.get("risk_factors") or [])
                    + [
                        c
                        for c in critique.get("concerns", [])
                        if c not in (decision.get("risk_factors") or [])
                    ],
                }
                return refined, tokens, cost

            return decision, tokens, cost

        except Exception:
            log_structured(
                "warning",
                "reasoning_critique_failed_using_original",
                trace_id=trace_id,
                exc_info=True,
            )
            return decision, 0, 0.0

    async def _call_llm(
        self,
        data: dict[str, Any],
        similar_trades: list[dict[str, Any]],
        trace_id: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int, float]:
        prompt = json.dumps(
            {
                "signal": data,
                "similar_trades": similar_trades,
                "ic_weights": (context or {}).get("ic_weights", {}),
                "risk_state": (context or {}).get("risk_state", {}),
            },
            default=str,
        )
        return await call_llm(prompt, trace_id)

    async def _apply_fallback(
        self, data: dict[str, Any], trace_id: str, reason: str
    ) -> dict[str, Any]:
        base_action = str(data.get("action") or data.get("signal") or "hold").lower()
        composite_score = float(data.get("composite_score", 0.0) or 0.0)

        if settings.LLM_FALLBACK_MODE == LLM_FALLBACK_MODE_REJECT_SIGNAL:
            action = AgentAction.REJECT
        elif settings.LLM_FALLBACK_MODE == LLM_FALLBACK_MODE_USE_LAST_REFLECTION:
            reflection = await get_last_reflection()
            action = reflection.get("action", base_action) if reflection else base_action
            valid_actions = {
                AgentAction.BUY,
                AgentAction.SELL,
                AgentAction.HOLD,
                AgentAction.REJECT,
            }
            if action not in valid_actions:
                action = base_action if base_action not in {"none", ""} else AgentAction.HOLD
        else:
            action = base_action if base_action not in {"none", ""} else AgentAction.HOLD

        return {
            "action": action,
            "confidence": round(max(composite_score, 0.1), 4),
            "primary_edge": f"fallback:{settings.LLM_FALLBACK_MODE}",
            "risk_factors": [reason],
            "size_pct": round(max(float(data.get("size_pct", 0.01) or 0.01), 0.01), 4),
            "stop_atr_x": float(data.get("stop_atr_x", 1.5) or 1.5),
            "rr_ratio": float(data.get("rr_ratio", 2.0) or 2.0),
            "latency_ms": 0,
            "cost_usd": 0.0,
            "trace_id": trace_id,
            "fallback": True,
        }

    # ------------------------------------------------------------------
    # Unified persistence — single routing point per operation
    # ------------------------------------------------------------------

    async def _persist_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        is_fallback: bool,
        today: str,
        tokens_used: int,
        cost_usd: float,
    ) -> str:
        """Persist agent run and cost tracking. Routes DB vs memory, returns agent_run_id."""
        if is_db_available():
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    agent_run_id = await self._db_store_agent_run(
                        data, summary, trace_id, is_fallback, session
                    )
                    await self._db_store_cost_tracking(today, tokens_used, cost_usd, session)
            return agent_run_id
        return self._mem_store_agent_run(data, summary, trace_id, is_fallback)

    async def _persist_vector(
        self, signal_summary: str, embedding: list[float], summary: dict[str, Any]
    ) -> None:
        """Persist vector memory entry. Routes DB vs memory."""
        if is_db_available():
            try:
                async with AsyncSessionFactory() as vm_session:
                    async with vm_session.begin():
                        await self._db_store_vector_memory(
                            signal_summary, embedding, summary, vm_session
                        )
            except Exception:
                log_structured("warning", "vector_memory_insert_failed", exc_info=True)
        else:
            self._mem_store_vector_memory(signal_summary, embedding, summary)

    # --- DB path helpers (only called when is_db_available() is True) ---

    async def _db_store_agent_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        fallback: bool,
        session,
    ) -> str:
        result = await session.execute(
            text("""
                INSERT INTO agent_runs (
                    strategy_id, symbol, signal_data, action, confidence,
                    primary_edge, risk_factors, size_pct, stop_atr_x, rr_ratio,
                    latency_ms, cost_usd, trace_id, fallback,
                    source, schema_version, status
                ) VALUES (
                    :strategy_id, :symbol, :signal_data, :action, :confidence,
                    :primary_edge, :risk_factors, :size_pct, :stop_atr_x,
                    :rr_ratio, :latency_ms, :cost_usd, :trace_id, :fallback,
                    :source, :schema_version, 'running'
                ) RETURNING id
            """),
            {
                "strategy_id": data.get("strategy_id"),
                "symbol": data.get("symbol"),
                "signal_data": json.dumps(data, default=str),
                "action": summary["action"],
                "confidence": summary["confidence"],
                "primary_edge": summary["primary_edge"],
                "risk_factors": json.dumps(summary["risk_factors"], default=str),
                "size_pct": summary["size_pct"],
                "stop_atr_x": summary["stop_atr_x"],
                "rr_ratio": summary["rr_ratio"],
                "latency_ms": summary["latency_ms"],
                "cost_usd": summary["cost_usd"],
                "trace_id": trace_id,
                "fallback": fallback,
                "source": AGENT_REASONING,
                "schema_version": DB_SCHEMA_VERSION,
            },
        )
        return str(result.scalar_one())

    async def _db_store_cost_tracking(
        self, today: str, tokens_used: int, cost_usd: float, session
    ) -> None:
        try:
            await session.execute(
                text("""
                    INSERT INTO llm_cost_tracking (date, tokens_used, cost_usd)
                    VALUES (:date, :tokens_used, :cost_usd) RETURNING id
                """),
                {"date": today, "tokens_used": tokens_used, "cost_usd": cost_usd},
            )
        except Exception:
            log_structured("warning", "cost_tracking_insert_failed", exc_info=True)

    async def _db_store_vector_memory(
        self, content: str, embedding: list[float], summary: dict[str, Any], session
    ) -> None:
        await session.execute(
            text("""
                INSERT INTO vector_memory (content, embedding, metadata_, outcome)
                VALUES (
                    :content,
                    CAST(:embedding AS vector),
                    CAST(:metadata AS JSONB),
                    CAST(:outcome AS JSONB)
                ) RETURNING id
            """),
            {
                "content": content,
                "embedding": build_vector_literal(embedding),
                "metadata": json.dumps({"trace_id": summary["trace_id"]}),
                "outcome": json.dumps(
                    {"action": summary["action"], "confidence": summary["confidence"]}
                ),
            },
        )

    # --- Memory path helpers (only called when is_db_available() is False) ---

    def _mem_store_agent_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        fallback: bool,
    ) -> str:
        run_id = f"mem-{trace_id}"
        get_runtime_store().add_agent_run(
            {
                "id": run_id,
                "trace_id": trace_id,
                "symbol": data.get("symbol"),
                "action": summary.get("action"),
                "confidence": summary.get("confidence"),
                "fallback": fallback,
                "source": AGENT_REASONING,
                "status": "running",
            }
        )
        return run_id

    def _mem_store_vector_memory(
        self, content: str, embedding: list[float], summary: dict[str, Any]
    ) -> None:
        get_runtime_store().add_vector_memory(
            {
                "content": content,
                "embedding": embedding,
                "metadata": {"trace_id": summary.get("trace_id")},
                "outcome": {
                    "action": summary.get("action"),
                    "confidence": summary.get("confidence"),
                },
            }
        )
