"""Reasoning agent: makes trading decisions using LLM analysis of signals."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from api.config import settings
from api.constants import NO_ORDER_ACTIONS, AgentAction
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
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
            bus, dlq, stream="signals", group=DEFAULT_GROUP, consumer="reasoning-agent"
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        today = date.today().isoformat()
        trace_id = str(uuid.uuid4())

        budget_used = int(await self.redis.get(f"llm:tokens:{today}") or 0)
        signal_summary = self._build_signal_summary(data)
        embedding = await embed_text(signal_summary)

        try:
            similar_trades = await search_vector_memory(embedding)
        except Exception:
            log_structured("warning", "vector_memory_search_failed", exc_info=True)
            similar_trades = []

        fallback_reason = None
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

        async with AsyncSessionFactory() as session:
            async with session.begin():
                agent_run_id = await self._store_agent_run(
                    data, summary, trace_id, fallback_reason is not None, session
                )
                await self._store_cost_tracking(today, tokens_used, cost_usd, session)

        await write_agent_log(
            trace_id,
            "reasoning_summary",
            {**summary, "fallback_reason": fallback_reason, "source": "reasoning_agent"},
            agent_run_id=agent_run_id,
        )

        # Vector memory is best-effort — separate session so failures do not abort the main write
        try:
            async with AsyncSessionFactory() as vm_session:
                async with vm_session.begin():
                    await self._store_vector_memory(signal_summary, embedding, summary, vm_session)
        except Exception:
            pass

        log_structured(
            "info", "agent_transaction_success", trace_id=trace_id, action=summary.get("action")
        )

        await self.redis.incrby(f"llm:tokens:{today}", tokens_used)
        await self.redis.incrbyfloat(f"llm:cost:{today}", cost_usd)

        # Publish live cost metric for WebSocket dashboard clients
        try:
            current_cost = float(await self.redis.get(f"llm:cost:{today}") or 0.0)
            await self.bus.publish(
                "system_metrics",
                {
                    "type": "system_metric",
                    "metric_name": "llm_cost_today",
                    "value": current_cost,
                    "source": "reasoning_agent",
                },
            )
        except Exception:
            pass

        updated_budget = int(await self.redis.get(f"llm:tokens:{today}") or 0)
        if updated_budget >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            await self.bus.publish(
                "risk_alerts",
                {
                    "type": "llm_budget",
                    "message": "Daily LLM token budget exceeded",
                    "tokens_used": updated_budget,
                    "limit": settings.ANTHROPIC_DAILY_TOKEN_BUDGET,
                },
            )

        await self.bus.publish(
            "agent_logs",
            {"type": "agent_log", "msg_id": str(uuid.uuid4()), "source": "reasoning", **summary},
        )

        action = summary.get("action", "").lower()
        if action not in NO_ORDER_ACTIONS:
            # strategy_id must be a non-empty UUID; fall back to a generated one if the
            # upstream signal didn't carry one (signals from SignalGenerator don't include it).
            strategy_id = str(data.get("strategy_id") or uuid.uuid4())
            await self.bus.publish(
                "orders",
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": "reasoning",
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

        if settings.LLM_FALLBACK_MODE == "reject_signal":
            action = "reject"
        elif settings.LLM_FALLBACK_MODE == "use_last_reflection":
            reflection = await get_last_reflection()
            action = reflection.get("action", base_action) if reflection else base_action
            valid_actions = {
                AgentAction.BUY,
                AgentAction.SELL,
                AgentAction.HOLD,
                AgentAction.REJECT,
            }
            if action not in valid_actions:
                action = base_action if base_action not in {"none", ""} else "hold"
        else:
            action = base_action if base_action not in {"none", ""} else "hold"

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

    async def _store_agent_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        fallback: bool,
        session,
    ) -> str:
        try:
            result = await session.execute(
                text("""
                    INSERT INTO agent_runs (
                        strategy_id, symbol, signal_data, action, confidence,
                        primary_edge, risk_factors, size_pct, stop_atr_x, rr_ratio,
                        latency_ms, cost_usd, trace_id, fallback
                    ) VALUES (
                        :strategy_id, :symbol, CAST(:signal_data AS JSONB), :action, :confidence,
                        :primary_edge, CAST(:risk_factors AS JSONB), :size_pct, :stop_atr_x,
                        :rr_ratio, :latency_ms, :cost_usd, :trace_id, :fallback
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
                },
            )
            return str(result.scalar_one())
        except Exception:
            log_structured("error", "agent_run_insert_failed", exc_info=True, trace_id=trace_id)
            raise

    async def _store_vector_memory(
        self, content: str, embedding: list[float], summary: dict[str, Any], session
    ) -> None:
        try:
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
        except Exception:
            log_structured(
                "error",
                "vector_memory_insert_failed",
                exc_info=True,
                trace_id=summary.get("trace_id"),
            )

    async def _store_cost_tracking(
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
            log_structured("error", "cost_tracking_insert_failed", exc_info=True)
            raise
