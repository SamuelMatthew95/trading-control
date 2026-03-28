"""Market data ingestion backed by pluggable real providers."""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from alpaca.data.live.crypto import CryptoDataStream
from alpaca.data.live.stock import StockDataStream

from api.config import settings
from api.events.bus import EventBus
from api.observability import log_structured

SUPPORTED_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY")


class MarketDataProvider(ABC):
    @abstractmethod
    async def stream_ticks(self) -> AsyncIterator[dict[str, Any]]:
        """Yield normalized tick payloads from external providers."""


class AlpacaProvider(MarketDataProvider):
    def __init__(self) -> None:
        if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY are required when MARKET_DATA_PROVIDER=alpaca. "
                "Set both env vars before starting the API."
            )
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10_000)

    async def stream_ticks(self) -> AsyncIterator[dict[str, Any]]:
        stock_stream = StockDataStream(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)
        crypto_stream = CryptoDataStream(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)

        async def enqueue_tick(payload: dict[str, Any]) -> None:
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:
                log_structured("warning", "alpaca_tick_queue_full")

        async def on_stock_bar(bar: Any) -> None:
            symbol = str(getattr(bar, "symbol", "")).upper()
            if symbol not in {"AAPL", "TSLA", "SPY"}:
                return
            await enqueue_tick(
                {
                    "symbol": symbol,
                    "price": str(getattr(bar, "close", "0")),
                    "volume": str(getattr(bar, "volume", "0")),
                    "timestamp": str(getattr(bar, "timestamp", datetime.now(timezone.utc).isoformat())),
                    "source": "alpaca",
                    "msg_id": str(uuid.uuid4()),
                }
            )

        async def on_crypto_bar(bar: Any) -> None:
            symbol = str(getattr(bar, "symbol", "")).upper().replace("BTCUSD", "BTC/USD").replace("ETHUSD", "ETH/USD").replace("SOLUSD", "SOL/USD")
            if symbol not in {"BTC/USD", "ETH/USD", "SOL/USD"}:
                return
            await enqueue_tick(
                {
                    "symbol": symbol,
                    "price": str(getattr(bar, "close", "0")),
                    "volume": str(getattr(bar, "volume", "0")),
                    "timestamp": str(getattr(bar, "timestamp", datetime.now(timezone.utc).isoformat())),
                    "source": "alpaca",
                    "msg_id": str(uuid.uuid4()),
                }
            )

        stock_stream.subscribe_bars(on_stock_bar, "AAPL", "TSLA", "SPY")
        crypto_stream.subscribe_bars(on_crypto_bar, "BTC/USD", "ETH/USD", "SOL/USD")

        stock_task = asyncio.create_task(stock_stream._run_forever(), name="alpaca-stock-bars")
        crypto_task = asyncio.create_task(crypto_stream._run_forever(), name="alpaca-crypto-bars")

        try:
            while True:
                yield await self._queue.get()
        finally:
            stock_task.cancel()
            crypto_task.cancel()
            with suppress(asyncio.CancelledError):
                await stock_task
            with suppress(asyncio.CancelledError):
                await crypto_task


class PolygonProvider(MarketDataProvider):
    async def stream_ticks(self) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("PolygonProvider is reserved for future implementation")


class MarketDataIngestor:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.interval = settings.MARKET_TICK_INTERVAL_SECONDS
        self._task: asyncio.Task[None] | None = None
        self._running = False
        provider_name = (settings.MARKET_DATA_PROVIDER or "alpaca").lower()
        if provider_name == "alpaca":
            self.provider: MarketDataProvider = AlpacaProvider()
        elif provider_name == "polygon":
            self.provider = PolygonProvider()
        else:
            raise RuntimeError(f"Unsupported MARKET_DATA_PROVIDER={provider_name}")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="market-data-ingestor")
        log_structured("info", "market_data_ingestor_started", symbols=list(SUPPORTED_SYMBOLS))

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        async for tick in self.provider.stream_ticks():
            if not self._running:
                break
            await self.bus.publish("market_ticks", tick, maxlen=10_000)


class MarketIngestor(MarketDataIngestor):
    """Backward compatible alias for legacy imports."""

