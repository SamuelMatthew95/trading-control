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
        self.symbols = list(self.SYMBOLS.keys())
        self.interval = settings.MARKET_TICK_INTERVAL_SECONDS

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        log_structured("info", "MarketIngestor starting", symbols=self.symbols, interval_seconds=self.interval)
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
                await self.bus.publish("market_ticks", tick, maxlen=1000)
            else:
                log_structured("debug", "Rejected invalid paper tick", tick=tick)
            await asyncio.sleep(self.interval)

    def _is_valid_tick(self, tick: dict[str, Any]) -> bool:
        try:
            timestamp = datetime.fromisoformat(str(tick["timestamp"]))
            age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
        except Exception:  # noqa: BLE001
            return False
        return (
            (tick.get("symbol") in self.SYMBOLS or tick.get("symbol") in ["SPY", "AAPL", "NVDA"])
            and float(tick.get("price", 0)) > 0
            and float(tick.get("bid", 0)) > 0
            and float(tick.get("ask", 0)) > 0
            and float(tick.get("ask", 0)) >= float(tick.get("bid", 0))
            and tick.get("source", "paper") in {"paper", "alpaca_live"}
            and age_seconds < 60
        )

    async def _connect_live(self) -> None:
        """Connect to Alpaca live market data stream."""
        from api.services.market_data_stream import AlpacaStream

        async def on_tick(tick: dict) -> None:
            if self._is_valid_tick(tick):
                await self.bus.publish("market_ticks", tick, maxlen=1000)
                log_structured("debug", "Live tick published",
                              symbol=tick["symbol"], price=tick["price"])
            else:
                log_structured("debug", "Live tick rejected", tick=tick)

        stream = AlpacaStream(on_tick=on_tick)
        log_structured("info", "Starting Alpaca live stream")
        await stream.start()
