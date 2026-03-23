"""Alpaca WebSocket market data stream."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import aiohttp

from api.config import settings
from api.observability import log_structured

# Only stock symbols — strip crypto
LIVE_SYMBOLS = ["SPY", "AAPL", "NVDA"]


class AlpacaStream:
    """
    Streams real-time market data from Alpaca IEX feed.
    Free tier — real prices, 15min delayed for stocks but
    good enough for paper trading signals.
    """

    def __init__(self, on_tick: Callable[[dict[str, Any]], None]):
        self.on_tick = on_tick
        self._running = False
        self.ws_url = settings.ALPACA_WS_URL

    async def start(self) -> None:
        self._running = True
        backoff = 1
        while self._running:
            try:
                await self._connect()
                backoff = 1  # reset on successful connection
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_structured(
                    "warning", "alpaca_stream_reconnecting",
                    backoff=backoff, exc_info=True
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def stop(self) -> None:
        self._running = False

    async def _connect(self) -> None:
        log_structured(
            "info", "Connecting to Alpaca WebSocket stream",
            symbols=LIVE_SYMBOLS,
        )
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.ws_url) as ws:
                # Authenticate
                await ws.send_json({
                    "action": "auth",
                    "key": settings.ALPACA_API_KEY,
                    "secret": settings.ALPACA_SECRET_KEY,
                })
                auth_msg = await ws.receive_json()
                log_structured("info", "Alpaca auth response", msg=auth_msg)

                # Subscribe to quotes
                await ws.send_json({
                    "action": "subscribe",
                    "quotes": LIVE_SYMBOLS,
                    "trades": LIVE_SYMBOLS,
                })
                log_structured(
                    "info", "Alpaca stream subscribed",
                    symbols=LIVE_SYMBOLS,
                )

                async for msg in ws:
                    if not self._running:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        for event in data if isinstance(data, list) else [data]:
                            await self._handle_event(event)

    async def _handle_event(self, event: dict[str, Any]) -> None:
        msg_type = event.get("T")

        if msg_type == "q":  # quote
            tick = {
                "symbol": event.get("S"),
                "price": float(event.get("ap", event.get("bp", 0))),
                "bid": float(event.get("bp", 0)),
                "ask": float(event.get("ap", 0)),
                "volume": 0.0,
                "timestamp": event.get("t"),
                "source": "alpaca_live",
            }
            if tick["price"] > 0:
                await self.on_tick(tick)

        elif msg_type == "t":  # trade
            tick = {
                "symbol": event.get("S"),
                "price": float(event.get("p", 0)),
                "bid": float(event.get("p", 0)),
                "ask": float(event.get("p", 0)),
                "volume": float(event.get("s", 0)),
                "timestamp": event.get("t"),
                "source": "alpaca_live",
            }
            if tick["price"] > 0:
                await self.on_tick(tick)

        elif msg_type == "error":
            log_structured("error", "Alpaca stream error", extra_data=event)

        elif msg_type in {"success", "subscription"}:
            log_structured(
                "info", "Alpaca stream status",
                msg_type=msg_type,
                extra_data=event,
            )
