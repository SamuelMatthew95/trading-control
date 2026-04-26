"""Paper broker backed by Redis state."""

from __future__ import annotations

import json
import random
import uuid
from typing import Any

from redis.asyncio import Redis

from api.constants import (
    DEFAULT_PAPER_CASH,
    REDIS_KEY_PAPER_CASH,
    REDIS_KEY_PAPER_ORDER,
    REDIS_KEY_PAPER_POSITION,
    FieldName,
    OrderSide,
    OrderStatus,
    PositionSide,
)


class PaperBroker:
    # Class attributes kept for backward compatibility; values come from module constants
    CASH_KEY = REDIS_KEY_PAPER_CASH
    DEFAULT_CASH = DEFAULT_PAPER_CASH

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict[str, Any]:
        await self.redis.setnx(REDIS_KEY_PAPER_CASH, DEFAULT_PAPER_CASH)
        normalized_side = side.lower()
        # Slippage is a fraction of price (0.01%–0.05%), not an absolute amount.
        # Without this, BTC at $60,000 gets $0.0003 slippage — effectively zero.
        slippage_pct = random.uniform(0.0001, 0.0005)
        direction = 1 if normalized_side in {OrderSide.BUY, PositionSide.LONG} else -1
        fill_price = round(price * (1 + direction * slippage_pct), 8)
        notional = qty * fill_price
        cash = await self.get_cash()
        if direction > 0:
            cash -= notional
        else:
            cash += notional
        await self.redis.set(REDIS_KEY_PAPER_CASH, cash)
        current_position = await self.get_position(symbol)
        current_qty = float(current_position.get(FieldName.QTY, 0.0))
        new_qty = current_qty + (qty * direction)
        position_payload = {
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: PositionSide.LONG if new_qty >= 0 else PositionSide.SHORT,
            FieldName.QTY: new_qty,
            FieldName.ENTRY_PRICE: fill_price,
            "current_price": fill_price,
        }
        await self.redis.set(
            REDIS_KEY_PAPER_POSITION.format(symbol=symbol), json.dumps(position_payload)
        )
        broker_order_id = str(uuid.uuid4())
        order_payload = {
            FieldName.BROKER_ORDER_ID: broker_order_id,
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: normalized_side,
            "filled_qty": qty,
            FieldName.FILL_PRICE: fill_price,
            FieldName.STATUS: OrderStatus.FILLED,
        }
        await self.redis.set(
            REDIS_KEY_PAPER_ORDER.format(broker_order_id=broker_order_id),
            json.dumps(order_payload),
        )
        return order_payload

    async def get_position(self, symbol: str) -> dict[str, Any]:
        raw = await self.redis.get(REDIS_KEY_PAPER_POSITION.format(symbol=symbol))
        if not raw:
            return {
                FieldName.SYMBOL: symbol,
                FieldName.SIDE: PositionSide.FLAT,
                FieldName.QTY: 0.0,
                FieldName.ENTRY_PRICE: 0.0,
                "current_price": 0.0,
            }
        return json.loads(raw)

    async def get_cash(self) -> float:
        await self.redis.setnx(REDIS_KEY_PAPER_CASH, DEFAULT_PAPER_CASH)
        return float(await self.redis.get(REDIS_KEY_PAPER_CASH) or DEFAULT_PAPER_CASH)

    async def get_order_status(self, broker_order_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(REDIS_KEY_PAPER_ORDER.format(broker_order_id=broker_order_id))
        return json.loads(raw) if raw else None
