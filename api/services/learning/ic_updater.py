"""Nightly information-coefficient updater for factor weights."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from math import isnan
from typing import Any

from sqlalchemy import text

from api.db import AsyncSessionFactory
from api.observability import log_structured


class ICUpdater:
    def __init__(self, redis_client):
        self.redis = redis_client
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="ic-updater")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self, reference_dt: datetime | None = None) -> dict[str, float]:
        now = reference_dt or datetime.now(timezone.utc)
        since = now - timedelta(days=30)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text(
                    "SELECT factor_attribution, pnl FROM trade_performance WHERE created_at >= :since ORDER BY created_at ASC"
                ),
                {"since": since},
            )
            rows = result.all()

            grouped: defaultdict[str, list[tuple[float, float]]] = defaultdict(list)
            for factor_attribution, pnl in rows:
                parsed = self._json_value(factor_attribution)
                realized_return = float(pnl or 0.0)
                for factor_name, score in parsed.items():
                    try:
                        grouped[str(factor_name)].append((float(score), realized_return))
                    except (TypeError, ValueError):
                        continue

            ic_scores: dict[str, float] = {
                factor_name: round(self._spearman(pairs), 6)
                for factor_name, pairs in grouped.items()
            }
            positive = {
                factor: max(score, 0.0)
                for factor, score in ic_scores.items()
                if not isnan(score)
            }
            total = sum(positive.values())
            weights = {
                factor: round(value / total, 6) if total > 0 else 0.0
                for factor, value in sorted(positive.items())
            }

            for factor_name, ic_score in ic_scores.items():
                await session.execute(
                    text(
                        "INSERT INTO factor_ic_history (factor_name, ic_score, computed_at) VALUES (:factor_name, :ic_score, :computed_at)"
                    ),
                    {
                        "factor_name": factor_name,
                        "ic_score": ic_score,
                        "computed_at": now,
                    },
                )
            await session.commit()

        await self.redis.set("alpha:ic_weights", json.dumps(weights, default=str))
        return weights

    async def _run_loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                next_midnight = datetime(
                    now.year, now.month, now.day, tzinfo=timezone.utc
                ) + timedelta(days=1)
                await asyncio.sleep(max((next_midnight - now).total_seconds(), 1))
                await self.run_once(next_midnight)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log_structured("warning", "IC updater failed", error=str(exc))

    def _spearman(self, pairs: list[tuple[float, float]]) -> float:
        if len(pairs) < 2:
            return 0.0
        xs = [score for score, _ in pairs]
        ys = [ret for _, ret in pairs]
        rx = self._ranks(xs)
        ry = self._ranks(ys)
        mean_rx = sum(rx) / len(rx)
        mean_ry = sum(ry) / len(ry)
        numerator = sum((x - mean_rx) * (y - mean_ry) for x, y in zip(rx, ry))
        denom_x = sum((x - mean_rx) ** 2 for x in rx) ** 0.5
        denom_y = sum((y - mean_ry) ** 2 for y in ry) ** 0.5
        if denom_x == 0 or denom_y == 0:
            return 0.0
        return numerator / (denom_x * denom_y)

    def _ranks(self, values: list[float]) -> list[float]:
        order = sorted(enumerate(values), key=lambda item: item[1])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
                j += 1
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[order[k][0]] = avg_rank
            i = j + 1
        return ranks

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
