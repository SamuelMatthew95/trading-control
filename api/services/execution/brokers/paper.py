"""Paper broker backed by Redis state."""

from __future__ import annotations

import json
import random
import uuid
from typing import Any

from redis.asyncio import Redis


class PaperBroker:
    CASH_KEY = "paper:cash"
    POSITION_KEY_PREFIX = "paper:positions:"
    ORDER_KEY_PREFIX = "paper:order:"
    DEFAULT_CASH = 100000.0

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def place_order(
        self, symbol: str, side: str, qty: float, price: float
    ) -> dict[str, Any]:
        await self.redis.setnx(self.CASH_KEY, self.DEFAULT_CASH)
        normalized_side = side.lower()
        slippage = random.uniform(0.0001, 0.0005)
        direction = 1 if normalized_side in {"buy", "long"} else -1
        fill_price = round(price + (direction * slippage), 8)
        notional = qty * fill_price
        cash = await self.get_cash()
        if direction > 0:
            cash -= notional
        else:
            cash += notional
        await self.redis.set(self.CASH_KEY, cash)
        position_key = f"{self.POSITION_KEY_PREFIX}{symbol}"
        current_position = await self.get_position(symbol)
        current_qty = float(current_position.get("qty", 0.0))
        new_qty = current_qty + (qty * direction)
        position_payload = {
            "symbol": symbol,
            "side": "long" if new_qty >= 0 else "short",
            "qty": new_qty,
            "entry_price": fill_price,
            "current_price": fill_price,
        }
        await self.redis.set(position_key, json.dumps(position_payload))
        broker_order_id = str(uuid.uuid4())
        order_payload = {
            "broker_order_id": broker_order_id,
            "symbol": symbol,
            "side": normalized_side,
            "filled_qty": qty,
            "fill_price": fill_price,
            "status": "filled",
        }
        await self.redis.set(
            f"{self.ORDER_KEY_PREFIX}{broker_order_id}", json.dumps(order_payload)
        )
        return order_payload

    async def get_position(self, symbol: str) -> dict[str, Any]:
        raw = await self.redis.get(f"{self.POSITION_KEY_PREFIX}{symbol}")
        if not raw:
            return {
                "symbol": symbol,
                "side": "flat",
                "qty": 0.0,
                "entry_price": 0.0,
                "current_price": 0.0,
            }
        return json.loads(raw)

    async def get_cash(self) -> float:
        await self.redis.setnx(self.CASH_KEY, self.DEFAULT_CASH)
        return float(await self.redis.get(self.CASH_KEY) or self.DEFAULT_CASH)

    async def get_order_status(self, broker_order_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(f"{self.ORDER_KEY_PREFIX}{broker_order_id}")
        return json.loads(raw) if raw else None
