"""Periodic market tick simulator for bootstrapping stream-based agent pipeline."""

from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from datetime import datetime, timezone
from uuid import uuid4

from api.events.bus import EventBus
from api.observability import log_structured


class MarketTickSimulator:
    """Publishes simulated market_ticks events for core symbols every 10 seconds."""

    DEFAULT_SYMBOLS = {
        "BTC/USD": 67000.0,
        "ETH/USD": 3500.0,
        "SOL/USD": 145.0,
        "AAPL": 190.0,
        "TSLA": 180.0,
        "SPY": 520.0,
    }

    def __init__(self, bus: EventBus, *, interval_seconds: float = 10.0):
        self.bus = bus
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._prices = dict(self.DEFAULT_SYMBOLS)

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run(), name="market-tick-simulator")
        log_structured(
            "info",
            "market_tick_simulator_started",
            event_name="market_tick_simulator_started",
            symbols=list(self.DEFAULT_SYMBOLS.keys()),
            interval_seconds=self.interval_seconds,
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def stop(self) -> None:
        self._running = False
        if not self._task:
            return

        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while self._running:
            for symbol, base_price in self.DEFAULT_SYMBOLS.items():
                drift = random.gauss(0.0, 0.002)
                next_price = max(0.01, self._prices[symbol] * (1 + drift))
                self._prices[symbol] = next_price
                tick = {
                    "msg_id": str(uuid4()),
                    "symbol": symbol,
                    "price": f"{next_price:.6f}",
                    "volume": f"{random.uniform(1.0, 150.0):.4f}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "simulator",
                }
                await self.bus.publish("market_ticks", tick, maxlen=1000)
            await asyncio.sleep(self.interval_seconds)
