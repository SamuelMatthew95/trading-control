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
    REDIS_KEY_LLM_COST,
    REDIS_KEY_LLM_TOKENS,
    SOURCE_REASONING,
    STREAM_AGENT_LOGS,
    STREAM_ORDERS,
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
from api.services.agents.vector_helpers import (
    build_vector_literal,
    embed_text,
    search_vector_memory,
)
from api.services.llm_router import call_llm


class ReasoningAgent(BaseStreamConsumer):
    """Listens on the ``signals`` stream and publishes orders based on LLM decisions."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client):
        super().__init__(
            bus, dlq, stream=STREAM_SIGNALS, group=DEFAULT_GROUP, consumer="reasoning-agent"
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        today = date.today().isoformat()
        trace_id = str(uuid.uuid4())

        budget_used = int(await self.redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
        signal_summary = self._build_signal_summary(data)
        embedding = await embed_text(signal_summary)

        try:
            similar_trades = await search_vector_memory(embedding)
        except Exception:
            log_structured("warning", "vector_memory_search_failed", exc_info=True)
            similar_trades = []

        # --- LLM decision ------------------------------------------------
        fallback_reason: str | None = None
        if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            fallback_reason = "budget_exceeded"
            summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
            tokens_used, cost_usd = 0, 0.0
        else:
            try:
                summary, tokens_used, cost_usd = await self._call_llm(
                    data, similar_trades, trace_id
                )
            except Exception as exc:  # noqa: BLE001
                fallback_reason = str(exc)
                summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
                tokens_used, cost_usd = 0, 0.0

        is_fallback = fallback_reason is not None

        # --- Persist agent run + cost tracking ---------------------------
        # Route is determined once here; no try/except used for routing.
        if is_db_available():
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    agent_run_id = await self._db_store_agent_run(
                        data, summary, trace_id, is_fallback, session
                    )
                    await self._db_store_cost_tracking(today, tokens_used, cost_usd, session)
        else:
            agent_run_id = self._mem_store_agent_run(data, summary, trace_id, is_fallback)

        # --- Agent log ---------------------------------------------------
        await write_agent_log(
            trace_id,
            "reasoning_summary",
            {**summary, "fallback_reason": fallback_reason, "source": SOURCE_REASONING},
            agent_run_id=agent_run_id,
        )

        # --- Vector memory (best-effort) ---------------------------------
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

        # --- Publish order if actionable ---------------------------------
        action = summary.get("action", "").lower()
        if action not in NO_ORDER_ACTIONS:
            strategy_id = str(data.get("strategy_id") or uuid.uuid4())
            await self.bus.publish(
                STREAM_ORDERS,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_REASONING,
                    "strategy_id": strategy_id,
                    "symbol": data.get("symbol"),
                    "side": action,
                    "qty": max(float(data.get("qty", 1.0)), float(summary.get("size_pct", 1.0))),
                    "price": float(data.get("price", data.get("last_price", 0.0))),
                    "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    "trace_id": trace_id,
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
                "signal_type": data.get("signal_type"),
                "context": data.get("context", {}),
            },
            sort_keys=True,
            default=str,
        )

    async def _call_llm(
        self, data: dict[str, Any], similar_trades: list[dict[str, Any]], trace_id: str
    ) -> tuple[dict[str, Any], int, float]:
        prompt = json.dumps({"signal": data, "similar_trades": similar_trades}, default=str)
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
