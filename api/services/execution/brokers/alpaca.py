"""Alpaca broker - live paper trading with real market prices."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from api.config import settings
from api.constants import (
    ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS,
    ALPACA_HTTP_READ_TIMEOUT_SECONDS,
    FieldName,
    OrderSide,
    OrderStatus,
    PositionSide,
)
from api.observability import log_structured

# Shared timeout for all aiohttp sessions — prevents indefinite blocking on
# Alpaca order endpoints when the upstream is slow or the connection is stale.
_AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    connect=float(ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS),
    sock_read=float(ALPACA_HTTP_READ_TIMEOUT_SECONDS),
    total=60.0,  # hard cap per request including retries
)


class AlpacaBroker:
    """
    Drop-in replacement for PaperBroker using Alpaca paper trading.
    Returns same shape as PaperBroker.place_order().
    Uses real market prices but fake money.
    """

    def __init__(self):
        self.base_url = settings.ALPACA_BASE_URL
        self.headers = {
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
            "Content-Type": "application/json",
        }

    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict[str, Any]:
        """Place order via Alpaca paper trading API."""
        # Normalize symbol - Alpaca uses "AAPL" not "AAPL/USD"
        alpaca_symbol = symbol.replace("/USD", "").replace("/", "")

        payload = {
            FieldName.SYMBOL: alpaca_symbol,
            FieldName.QTY: str(round(qty, 6)),
            FieldName.SIDE: OrderSide.BUY
            if side.lower() in {OrderSide.BUY, PositionSide.LONG}
            else OrderSide.SELL,
            FieldName.TYPE: "market",
            FieldName.TIME_IN_FORCE: "day",
        }

        log_structured(
            "info",
            "Placing Alpaca order",
            symbol=alpaca_symbol,
            side=payload[FieldName.SIDE],
            qty=qty,
        )

        async with aiohttp.ClientSession(timeout=_AIOHTTP_TIMEOUT) as session:
            async with session.post(
                f"{self.base_url}/v2/orders",
                headers=self.headers,
                json=payload,
            ) as resp:
                body = await resp.json()

                if resp.status >= 400:
                    log_structured(
                        "error",
                        "Alpaca order rejected",
                        symbol=alpaca_symbol,
                        status=resp.status,
                        error=body.get(FieldName.MESSAGE, "unknown"),
                    )
                    raise RuntimeError(
                        f"Alpaca order failed {resp.status}: {body.get(FieldName.MESSAGE)}"
                    )

        broker_order_id = body[FieldName.ID]
        log_structured(
            "info",
            "Alpaca order placed, waiting for fill",
            broker_order_id=broker_order_id,
            symbol=alpaca_symbol,
        )

        # Poll for fill - market orders fill fast, max 10 attempts
        fill_price = price  # fallback to signal price
        status = "pending"
        for attempt in range(10):
            await asyncio.sleep(0.5)  # Order fill polling - allowed
            async with aiohttp.ClientSession(timeout=_AIOHTTP_TIMEOUT) as session:
                async with session.get(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self.headers,
                ) as resp:
                    order = await resp.json()

            status = order.get(FieldName.STATUS, "pending")
            filled_avg_price = order.get(FieldName.FILLED_AVG_PRICE)

            if status == OrderStatus.FILLED and filled_avg_price:
                fill_price = float(filled_avg_price)
                log_structured(
                    "info",
                    "Alpaca order filled",
                    broker_order_id=broker_order_id,
                    symbol=alpaca_symbol,
                    fill_price=fill_price,
                    attempt=attempt + 1,
                )
                break
            if status in {"canceled", "expired", "rejected"}:
                log_structured(
                    "warning",
                    "Alpaca order terminal state",
                    broker_order_id=broker_order_id,
                    symbol=alpaca_symbol,
                    status=status,
                )
                break

            log_structured(
                "debug",
                "Waiting for Alpaca fill",
                broker_order_id=broker_order_id,
                status=status,
                attempt=attempt + 1,
            )

        filled_qty = float(order.get(FieldName.FILLED_QTY) or qty)

        return {
            FieldName.BROKER_ORDER_ID: broker_order_id,
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: side.lower(),
            FieldName.FILLED_QTY: filled_qty,
            FieldName.FILL_PRICE: fill_price,
            FieldName.STATUS: status if status == OrderStatus.FILLED else OrderStatus.PENDING,
        }

    async def get_position(self, symbol: str) -> dict[str, Any]:
        """Get current position from Alpaca."""
        alpaca_symbol = symbol.replace("/USD", "").replace("/", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/v2/positions/{alpaca_symbol}",
                headers=self.headers,
            ) as resp:
                if resp.status == 404:
                    return {
                        FieldName.SYMBOL: symbol,
                        FieldName.SIDE: PositionSide.FLAT,
                        FieldName.QTY: 0.0,
                        FieldName.ENTRY_PRICE: 0.0,
                        FieldName.CURRENT_PRICE: 0.0,
                    }
                body = await resp.json()
                return {
                    FieldName.SYMBOL: symbol,
                    FieldName.SIDE: body.get(FieldName.SIDE, "flat"),
                    FieldName.QTY: float(body.get(FieldName.QTY, 0.0)),
                    FieldName.ENTRY_PRICE: float(body.get(FieldName.AVG_ENTRY_PRICE, 0.0)),
                    FieldName.CURRENT_PRICE: float(body.get(FieldName.CURRENT_PRICE, 0.0)),
                }

    async def get_cash(self) -> float:
        """Get available buying power from Alpaca account."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/v2/account",
                headers=self.headers,
            ) as resp:
                body = await resp.json()
                return float(body.get(FieldName.BUYING_POWER, 0.0))

    async def get_order_status(self, broker_order_id: str) -> dict[str, Any] | None:
        """Get order status from Alpaca."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/v2/orders/{broker_order_id}",
                headers=self.headers,
            ) as resp:
                if resp.status == 404:
                    return None
                body = await resp.json()
                return {
                    FieldName.BROKER_ORDER_ID: broker_order_id,
                    FieldName.SYMBOL: body.get(FieldName.SYMBOL),
                    FieldName.SIDE: body.get(FieldName.SIDE),
                    FieldName.FILLED_QTY: float(body.get(FieldName.FILLED_QTY) or 0),
                    FieldName.FILL_PRICE: float(body.get(FieldName.FILLED_AVG_PRICE) or 0),
                    FieldName.STATUS: body.get(FieldName.STATUS),
                }
