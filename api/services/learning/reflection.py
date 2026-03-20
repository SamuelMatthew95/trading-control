"""Batch trade reflection loop for learning summaries."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timezone
from statistics import mean
from typing import Any

import aiohttp
from sqlalchemy import text

from api.config import settings
from api.db import AsyncSessionFactory
from api.events.bus import EventBus
from api.observability import log_structured

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class ReflectionService:
    def __init__(self, bus: EventBus, redis_client, poll_interval_seconds: int = 5):
        self.bus = bus
        self.redis = redis_client
        self.poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="reflection-service")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> bool:
        trade_count = int(await self.redis.get("reflection:trade_count") or 0)
        if trade_count < settings.REFLECTION_TRADE_THRESHOLD:
            return False

        trades = await self._fetch_recent_trades(settings.REFLECTION_TRADE_THRESHOLD)
        if not trades:
            return False

        payload = await self._build_reflection_payload(trades)
        trace_id = f"reflection_{datetime.now(timezone.utc).isoformat()}"

        async with AsyncSessionFactory() as session:
            await session.execute(
                text(
                    "INSERT INTO agent_logs (trace_id, log_type, payload) VALUES (:trace_id, 'reflection', CAST(:payload AS JSONB))"
                ),
                {
                    "trace_id": trace_id,
                    "payload": json.dumps(
                        {
                            **payload,
                            "type": "reflection",
                            "trade_count": len(trades),
                        },
                        default=str,
                    ),
                },
            )
            await session.commit()

        await self.redis.set("reflection:trade_count", 0)
        await self.bus.publish(
            "agent_logs",
            {
                "type": "agent_log",
                "log_type": "reflection",
                "trace_id": trace_id,
                **payload,
            },
        )
        await self.bus.publish(
            "learning_events",
            {
                "type": "learning_event",
                "event": "reflection_completed",
                "trace_id": trace_id,
                "summary": payload.get("summary"),
            },
        )
        return True

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                log_structured("warning", "Reflection service failed", error=str(exc))
            await asyncio.sleep(self.poll_interval_seconds)

    async def _fetch_recent_trades(self, limit: int) -> list[dict[str, Any]]:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text(
                    "SELECT tp.symbol, tp.pnl, tp.holding_secs, tp.factor_attribution, tp.market_context, tp.created_at "
                    "FROM trade_performance tp ORDER BY tp.created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [
                {
                    "symbol": row[0],
                    "pnl": float(row[1]),
                    "holding_secs": int(row[2]),
                    "factor_attribution": self._json_value(row[3]),
                    "market_context": self._json_value(row[4]),
                    "created_at": row[5],
                }
                for row in result.all()
            ]

    async def _build_reflection_payload(
        self, trades: list[dict[str, Any]]
    ) -> dict[str, Any]:
        fallback = self._fallback_reflection(trades)
        if not settings.ANTHROPIC_API_KEY:
            return fallback

        prompt = {
            "trades": trades,
            "instruction": "Return JSON only with keys winning_factors, losing_factors, regime_edge, sizing_recommendation, new_hypotheses, summary.",
        }
        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 400,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": json.dumps(prompt, default=str)}],
        }
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.LLM_TIMEOUT_SECONDS)
            ) as session:
                async with session.post(
                    ANTHROPIC_URL,
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"anthropic_status_{response.status}")
                    body = await response.json()
            text_payload = "".join(
                block.get("text", "")
                for block in body.get("content", [])
                if block.get("type") == "text"
            )
            parsed = json.loads(text_payload)
            return {
                "winning_factors": parsed.get(
                    "winning_factors", fallback["winning_factors"]
                ),
                "losing_factors": parsed.get(
                    "losing_factors", fallback["losing_factors"]
                ),
                "regime_edge": parsed.get("regime_edge", fallback["regime_edge"]),
                "sizing_recommendation": parsed.get(
                    "sizing_recommendation", fallback["sizing_recommendation"]
                ),
                "new_hypotheses": parsed.get(
                    "new_hypotheses", fallback["new_hypotheses"]
                ),
                "summary": parsed.get("summary", fallback["summary"]),
            }
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Reflection LLM call failed", error=str(exc))
            return fallback

    def _fallback_reflection(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        wins: defaultdict[str, list[float]] = defaultdict(list)
        losses: defaultdict[str, list[float]] = defaultdict(list)
        for trade in trades:
            bucket = wins if float(trade.get("pnl", 0.0)) > 0 else losses
            for key, value in self._json_value(trade.get("factor_attribution")).items():
                try:
                    bucket[key].append(float(value))
                except (TypeError, ValueError):
                    continue

        def top_factors(
            source: defaultdict[str, list[float]]
        ) -> list[dict[str, float]]:
            ranked = sorted(
                ((key, mean(values)) for key, values in source.items() if values),
                key=lambda item: item[1],
                reverse=True,
            )
            return [
                {"factor": key, "score": round(score, 6)} for key, score in ranked[:3]
            ]

        avg_hold = round(
            mean([max(int(trade.get("holding_secs", 0)), 0) for trade in trades]), 2
        )
        return {
            "winning_factors": top_factors(wins),
            "losing_factors": top_factors(losses),
            "regime_edge": "paper-mode regime inference from recent trade batch",
            "sizing_recommendation": "increase only when top winning factors stay positive and lag stays low",
            "new_hypotheses": [
                "Favor signals whose positive factor cluster repeats across winning trades.",
                "Reduce size when recent losing factor cluster dominates consecutive trades.",
            ],
            "summary": f"Reflection batch analyzed {len(trades)} trades with average holding time {avg_hold} seconds.",
        }

    def _json_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return dict(value) if hasattr(value, "items") else {}
