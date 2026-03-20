"""Market data ingestion for paper-mode simulations."""

from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.events.bus import EventBus
from api.observability import log_structured


class MarketIngestor:
    SYMBOLS = {
        "BTC/USD": 67000.0,
        "ETH/USD": 3500.0,
        "SOL/USD": 145.0,
        "SPY": 510.0,
        "AAPL": 178.0,
        "NVDA": 875.0,
    }

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._prices = dict(self.SYMBOLS)
        self._running = False
        self._live_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        if settings.BROKER_MODE == "paper":
            for symbol in self.SYMBOLS:
                if symbol not in self._tasks or self._tasks[symbol].done():
                    self._tasks[symbol] = asyncio.create_task(
                        self._run_symbol(symbol), name=f"market:{symbol}"
                    )
            return

        self._live_task = asyncio.create_task(self._connect_live(), name="market:live")

    async def stop(self) -> None:
        self._running = False

        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

        if self._live_task is not None:
            self._live_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._live_task
            self._live_task = None

    async def _run_symbol(self, symbol: str) -> None:
        drift = 0.0
        while self._running:
            drift = (drift * 0.95) + random.gauss(0.0, 0.0001)
            self._prices[symbol] += random.gauss(drift, 0.0005)
            price = round(self._prices[symbol], 6)
            tick = {
                "symbol": symbol,
                "price": price,
                "bid": round(price - 0.01, 6),
                "ask": round(price + 0.01, 6),
                "volume": round(random.uniform(0.1, 10.0), 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "paper",
            }
            if self._is_valid_tick(tick):
                await self.bus.publish("market_ticks", tick)
            else:
                log_structured("debug", "Rejected invalid paper tick", tick=tick)
            await asyncio.sleep(0.25)

    def _is_valid_tick(self, tick: dict[str, Any]) -> bool:
        try:
            timestamp = datetime.fromisoformat(str(tick["timestamp"]))
            age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
        except Exception:  # noqa: BLE001
            return False

        return (
            tick.get("symbol") in self.SYMBOLS
            and float(tick.get("price", 0)) > 0
            and float(tick.get("bid", 0)) > 0
            and float(tick.get("ask", 0)) >= float(tick.get("bid", 0))
            and age_seconds < 60
        )

    async def _connect_live(self) -> None:
        backoff = 1
        while self._running:
            try:
                log_structured(
                    "info",
                    "Live market connector stub waiting for implementation",
                    backoff_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except asyncio.CancelledError:
                raise
