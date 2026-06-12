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
from api.telemetry import traced_broker_call


class PaperBroker:
    # Class attributes kept for backward compatibility; values come from module constants
    CASH_KEY = REDIS_KEY_PAPER_CASH
    DEFAULT_CASH = DEFAULT_PAPER_CASH

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    @traced_broker_call("place_order", "paper", is_order=True)
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
        prior_entry = float(current_position.get(FieldName.ENTRY_PRICE, 0.0) or 0.0)
        new_qty = current_qty + (qty * direction)

        # Compute the new entry price honestly. Previous code overwrote
        # entry_price to fill_price on EVERY order, which destroyed cost basis
        # after any partial close — the next sell would compute realized PnL
        # against the closing price instead of the original entry.
        if abs(new_qty) < 1e-9:
            new_entry_price = 0.0
            new_side = PositionSide.FLAT
        elif abs(current_qty) < 1e-9 or prior_entry <= 0:
            new_entry_price = fill_price
            new_side = PositionSide.LONG if new_qty > 0 else PositionSide.SHORT
        elif (current_qty > 0) == (direction > 0):
            # Adding in the same direction → weighted average cost
            new_entry_price = (prior_entry * abs(current_qty) + fill_price * qty) / abs(new_qty)
            new_side = PositionSide.LONG if new_qty > 0 else PositionSide.SHORT
        elif (current_qty > 0) != (new_qty > 0):
            # Order flipped direction past zero → new opening price
            new_entry_price = fill_price
            new_side = PositionSide.LONG if new_qty > 0 else PositionSide.SHORT
        else:
            # Reducing same-direction position (partial close) → preserve entry
            new_entry_price = prior_entry
            new_side = PositionSide.LONG if new_qty > 0 else PositionSide.SHORT

        position_payload = {
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: new_side,
            FieldName.QTY: new_qty,
            FieldName.ENTRY_PRICE: new_entry_price,
            FieldName.CURRENT_PRICE: fill_price,
        }
        await self.redis.set(
            REDIS_KEY_PAPER_POSITION.format(symbol=symbol), json.dumps(position_payload)
        )
        broker_order_id = str(uuid.uuid4())
        order_payload = {
            FieldName.BROKER_ORDER_ID: broker_order_id,
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: normalized_side,
            FieldName.FILLED_QTY: qty,
            FieldName.FILL_PRICE: fill_price,
            FieldName.STATUS: OrderStatus.FILLED,
        }
        await self.redis.set(
            REDIS_KEY_PAPER_ORDER.format(broker_order_id=broker_order_id),
            json.dumps(order_payload),
        )
        return order_payload

    @staticmethod
    def _flat_position(symbol: str) -> dict[str, Any]:
        """Zero/flat position shape returned when a symbol has no Redis entry."""
        return {
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: PositionSide.FLAT,
            FieldName.QTY: 0.0,
            FieldName.ENTRY_PRICE: 0.0,
            FieldName.CURRENT_PRICE: 0.0,
        }

    async def get_position(self, symbol: str) -> dict[str, Any]:
        raw = await self.redis.get(REDIS_KEY_PAPER_POSITION.format(symbol=symbol))
        if not raw:
            return self._flat_position(symbol)
        return json.loads(raw)

    async def get_positions(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-read positions for many symbols in a single MGET round trip.

        Replaces N sequential GETs (one per symbol) so a dashboard refresh does
        not hold N pooled Redis connections in series — the pattern that drained
        the pool and surfaced as "Too many connections" warnings on /positions
        and /pnl.
        """
        if not symbols:
            return {}
        keys = [REDIS_KEY_PAPER_POSITION.format(symbol=s) for s in symbols]
        raws = await self.redis.mget(keys)
        out: dict[str, dict[str, Any]] = {}
        for symbol, raw in zip(symbols, raws, strict=True):
            if raw:
                try:
                    out[symbol] = json.loads(raw)
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            out[symbol] = self._flat_position(symbol)
        return out

    async def get_cash(self) -> float:
        await self.redis.setnx(REDIS_KEY_PAPER_CASH, DEFAULT_PAPER_CASH)
        return float(await self.redis.get(REDIS_KEY_PAPER_CASH) or DEFAULT_PAPER_CASH)

    async def get_order_status(self, broker_order_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(REDIS_KEY_PAPER_ORDER.format(broker_order_id=broker_order_id))
        return json.loads(raw) if raw else None
