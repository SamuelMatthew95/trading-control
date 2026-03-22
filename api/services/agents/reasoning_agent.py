"""Structured reasoning agent for signal summaries."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

import aiohttp
from sqlalchemy import text

from api.config import settings
from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.llm_router import call_llm

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"
EMBED_DIMENSIONS = 1536


class ReasoningAgent(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client):
        super().__init__(
            bus, dlq, stream="signals", group=DEFAULT_GROUP, consumer="reasoning-agent"
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        today = date.today().isoformat()
        trace_id = str(uuid.uuid4())
        budget_key = f"llm:tokens:{today}"
        budget_used = int(await self.redis.get(budget_key) or 0)
        signal_summary = self._summarize_signal(data)
        embedding = await self._embed_text(signal_summary)
        similar_trades = await self._search_vector_memory(embedding)
        fallback_reason = None
        if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            fallback_reason = "budget_exceeded"
            summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
            tokens_used, cost_usd = 0, 0.0
        else:
            try:
                summary, tokens_used, cost_usd = await self._call_reasoning_model(
                    data, similar_trades, trace_id
                )
            except Exception as exc:  # noqa: BLE001
                fallback_reason = str(exc)
                summary = await self._apply_fallback(
                    data, trace_id, reason=fallback_reason
                )
                tokens_used, cost_usd = 0, 0.0
        await self._store_agent_run(
            data, summary, trace_id, fallback_reason is not None
        )
        await self._store_vector_memory(signal_summary, embedding, summary)
        await self._store_agent_log(trace_id, summary, fallback_reason)
        await self.redis.incrby(budget_key, tokens_used)
        await self.redis.incrbyfloat(f"llm:cost:{today}", cost_usd)
        await self._store_cost_tracking(today, tokens_used, cost_usd)
        if (
            int(await self.redis.get(budget_key) or 0)
            >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET
        ):
            await self.bus.publish(
                "risk_alerts",
                {
                    "type": "llm_budget",
                    "message": "Daily LLM token budget exceeded",
                    "tokens_used": int(await self.redis.get(budget_key) or 0),
                    "limit": settings.ANTHROPIC_DAILY_TOKEN_BUDGET,
                },
            )
        await self.bus.publish("agent_logs", {"type": "agent_log", **summary})
        if summary["action"].lower() not in {"reject", "hold", "flat"}:
            await self.bus.publish(
                "orders",
                {
                    "strategy_id": data.get("strategy_id"),
                    "symbol": data.get("symbol"),
                    "side": summary["action"].lower(),
                    "qty": max(
                        float(data.get("qty", 1.0)), float(summary.get("size_pct", 1.0))
                    ),
                    "price": float(data.get("price", data.get("last_price", 0.0))),
                    "timestamp": data.get(
                        "timestamp", datetime.now(timezone.utc).isoformat()
                    ),
                    "trace_id": trace_id,
                },
            )

    def _summarize_signal(self, data: dict[str, Any]) -> str:
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

    async def _embed_text(self, text_value: str) -> list[float]:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.LLM_TIMEOUT_SECONDS)
            ) as session:
                async with session.post(
                    OPENAI_EMBEDDING_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": "text-embedding-3-small", "input": text_value},
                ) as response:
                    if response.status >= 400:
                        raise RuntimeError(
                            f"Embedding API failed with status {response.status}"
                        )
                    payload = await response.json()
                    return payload["data"][0]["embedding"]
        digest = hashlib.sha256(text_value.encode("utf-8")).digest()
        values = []
        while len(values) < EMBED_DIMENSIONS:
            for byte in digest:
                values.append(round(byte / 255, 6))
                if len(values) == EMBED_DIMENSIONS:
                    break
        return values

    async def _search_vector_memory(
        self, embedding: list[float]
    ) -> list[dict[str, Any]]:
        vector_literal = self._vector_literal(embedding)
        query = text(
            "SELECT id, content, metadata_, outcome, 1 - (embedding <=> CAST(:embedding AS vector)) AS sim FROM vector_memory ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT 5"
        )
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(query, {"embedding": vector_literal})
                return [
                    {
                        "id": str(row["id"]),
                        "content": row["content"],
                        "metadata": row["metadata_"],
                        "outcome": row["outcome"],
                        "sim": float(row["sim"]),
                    }
                    for row in result.mappings().all()
                ]
        except Exception as exc:  # noqa: BLE001
            log_structured(
                "warning", "Vector memory search unavailable", error=str(exc)
            )
            return []

    async def _call_reasoning_model(
        self, data: dict[str, Any], similar_trades: list[dict[str, Any]], trace_id: str
    ) -> tuple[dict[str, Any], int, float]:
        prompt = json.dumps(
            {"signal": data, "similar_trades": similar_trades}, default=str
        )
        return await call_llm(prompt, trace_id)

    async def _apply_fallback(
        self, data: dict[str, Any], trace_id: str, reason: str
    ) -> dict[str, Any]:
        base_action = str(data.get("action") or data.get("signal") or "hold").lower()
        composite_score = float(data.get("composite_score", 0.0) or 0.0)
        if settings.LLM_FALLBACK_MODE == "reject_signal":
            action = "reject"
        elif settings.LLM_FALLBACK_MODE == "use_last_reflection":
            reflection = await self._get_last_reflection()
            # Extract proper action from reflection, not sizing_recommendation
            action = (
                reflection.get("action", base_action) if reflection else base_action
            )
            if action not in {"buy", "sell", "hold", "reject"}:
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

    async def _get_last_reflection(self) -> dict[str, Any]:
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text(
                        "SELECT payload FROM agent_logs WHERE log_type = 'reflection' ORDER BY created_at DESC LIMIT 1"
                    )
                )
                row = result.first()
                if row is None:
                    return {}
                payload = row[0]
                if isinstance(payload, str):
                    return json.loads(payload)
                return payload or {}
        except Exception:
            return {}

    async def _store_agent_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        fallback: bool,
    ) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text(
                        "INSERT INTO agent_runs (strategy_id, symbol, signal_data, action, confidence, primary_edge, risk_factors, size_pct, stop_atr_x, rr_ratio, latency_ms, cost_usd, trace_id, fallback) VALUES (:strategy_id, :symbol, CAST(:signal_data AS JSONB), :action, :confidence, :primary_edge, CAST(:risk_factors AS JSONB), :size_pct, :stop_atr_x, :rr_ratio, :latency_ms, :cost_usd, :trace_id, :fallback)"
                    ),
                    {
                        "strategy_id": data.get("strategy_id"),
                        "symbol": data.get("symbol"),
                        "signal_data": json.dumps(data, default=str),
                        "action": summary["action"],
                        "confidence": summary["confidence"],
                        "primary_edge": summary["primary_edge"],
                        "risk_factors": json.dumps(
                            summary["risk_factors"], default=str
                        ),
                        "size_pct": summary["size_pct"],
                        "stop_atr_x": summary["stop_atr_x"],
                        "rr_ratio": summary["rr_ratio"],
                        "latency_ms": summary["latency_ms"],
                        "cost_usd": summary["cost_usd"],
                        "trace_id": trace_id,
                        "fallback": fallback,
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store agent run", error=str(exc))

    async def _store_vector_memory(
        self, content: str, embedding: list[float], summary: dict[str, Any]
    ) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text(
                        "INSERT INTO vector_memory (content, embedding, metadata_, outcome) VALUES (:content, CAST(:embedding AS vector), CAST(:metadata AS JSONB), CAST(:outcome AS JSONB))"
                    ),
                    {
                        "content": content,
                        "embedding": self._vector_literal(embedding),
                        "metadata": json.dumps({"trace_id": summary["trace_id"]}),
                        "outcome": json.dumps(
                            {
                                "action": summary["action"],
                                "confidence": summary["confidence"],
                            }
                        ),
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store vector memory", error=str(exc))

    async def _store_agent_log(
        self, trace_id: str, summary: dict[str, Any], fallback_reason: str | None
    ) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text(
                        "INSERT INTO agent_logs (trace_id, log_type, payload) VALUES (:trace_id, :log_type, CAST(:payload AS JSONB))"
                    ),
                    {
                        "trace_id": trace_id,
                        "log_type": "reasoning_summary",
                        "payload": json.dumps(
                            {**summary, "fallback_reason": fallback_reason}, default=str
                        ),
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store agent log", error=str(exc))

    async def _store_cost_tracking(
        self, today: str, tokens_used: int, cost_usd: float
    ) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text(
                        "INSERT INTO llm_cost_tracking (date, tokens_used, cost_usd) VALUES (:date, :tokens_used, :cost_usd)"
                    ),
                    {"date": today, "tokens_used": tokens_used, "cost_usd": cost_usd},
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured(
                "warning", "Unable to store LLM cost tracking", error=str(exc)
            )

    def _vector_literal(self, embedding: list[float]) -> str:
        return "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
