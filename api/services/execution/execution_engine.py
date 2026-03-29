"""Order execution engine backed by the paper broker."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.execution.brokers.paper import PaperBroker

LARGE_ORDER_THRESHOLD = 10.0


class ExecutionEngine(BaseStreamConsumer):
    def __init__(
        self, bus: EventBus, dlq: DLQManager, redis_client: Redis, broker: PaperBroker
    ):
        super().__init__(
            bus, dlq, stream="orders", group=DEFAULT_GROUP, consumer="execution-engine"
        )
        self.redis = redis_client
        self.broker = broker

    async def process(self, data: dict[str, Any]) -> None:
        if await self.redis.get("kill_switch:active") == "1":
            raise RuntimeError("KillSwitchActive")

        strategy_id = str(data["strategy_id"])
        symbol = str(data["symbol"])
        side = str(data["side"]).lower()
        qty = float(data["qty"])
        price = float(data["price"])
        order_timestamp = self._parse_timestamp(data.get("timestamp"))
        idempotency_key = self._build_idempotency_key(
            strategy_id, symbol, side, order_timestamp, data
        )
        lock_key = f"order_lock:{symbol}"
        lock_value = str(uuid.uuid4())

        async with AsyncSessionFactory() as session:
            existing = await session.execute(
                text(
                    "SELECT id, status, broker_order_id, idempotency_key FROM orders WHERE idempotency_key = :idempotency_key"
                ),
                {"idempotency_key": idempotency_key},
            )
            existing_row = existing.mappings().first()
            if existing_row is not None:
                log_structured(
                    "info",
                    "Skipping duplicate order event",
                    idempotency_key=idempotency_key,
                    order_id=str(existing_row["id"]),
                )
                return

            lock_acquired = await self.redis.set(lock_key, lock_value, ex=5, nx=True)
            if not lock_acquired:
                raise RuntimeError(f"Order lock already held for {symbol}")

            order_id: str | None = None
            vwap_plan = self._build_vwap_plan(qty)
            try:
                inserted = await session.execute(
                    text(
                        "INSERT INTO orders (strategy_id, symbol, side, qty, price, status, idempotency_key, broker_order_id) VALUES (:strategy_id, :symbol, :side, :qty, :price, 'pending', :idempotency_key, NULL) RETURNING id"
                    ),
                    {
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "idempotency_key": idempotency_key,
                    },
                )
                order_id = str(inserted.scalar_one())
                await session.flush()

                broker_result = await self.broker.place_order(symbol, side, qty, price)
                filled_at = datetime.now(timezone.utc).replace(tzinfo=None)

                await session.execute(
                    text(
                        "UPDATE orders SET status = :status, broker_order_id = :broker_order_id, price = :fill_price, filled_at = :filled_at WHERE id = :order_id"
                    ),
                    {
                        "status": broker_result["status"],
                        "broker_order_id": broker_result["broker_order_id"],
                        "fill_price": broker_result["fill_price"],
                        "filled_at": filled_at,
                        "order_id": order_id,
                    },
                )
                await self._upsert_position(
                    session,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    fill_price=float(broker_result["fill_price"]),
                )
                await self._insert_audit_log(
                    session,
                    event_type="order_placed",
                    payload={
                        "order_id": order_id,
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "broker_order_id": broker_result["broker_order_id"],
                        "vwap_plan": vwap_plan,
                    },
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await self.redis.delete(lock_key)

        await self.bus.publish(
            "executions",
            {
                "type": "order_filled",
                "order_id": order_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "fill_price": float(broker_result["fill_price"]),
                "filled_at": filled_at.isoformat(),
                "idempotency_key": idempotency_key,
                "trace_id": data.get("trace_id"),
                "vwap_plan": vwap_plan,
            },
        )

    def _build_idempotency_key(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        timestamp: datetime,
        signal_data: dict[str, Any] | None = None,
    ) -> str:
        ts_minute = timestamp.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        # Include signal hash for better granularity
        signal_hash = ""
        if signal_data:
            signal_content = json.dumps(
                {
                    "composite_score": signal_data.get("composite_score"),
                    "signal_type": signal_data.get("signal_type"),
                    "price": signal_data.get("price"),
                    "qty": signal_data.get("qty"),
                },
                sort_keys=True,
                default=str,
            )
            signal_hash = hashlib.md5(signal_content.encode()).hexdigest()[:8]
        return f"{strategy_id}_{symbol}_{side}_{ts_minute}_{signal_hash}"

    def _build_vwap_plan(self, qty: float) -> list[float] | None:
        if qty <= LARGE_ORDER_THRESHOLD:
            return None
        slice_qty = round(qty / 3, 8)
        return [slice_qty, slice_qty, round(qty - (slice_qty * 2), 8)]

    def _parse_timestamp(self, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    async def _upsert_position(
        self,
        session,
        strategy_id: str,
        symbol: str,
        side: str,
        qty: float,
        fill_price: float,
    ) -> None:
        existing = await session.execute(
            text(
                "SELECT id, side, qty FROM positions WHERE strategy_id = :strategy_id AND symbol = :symbol"
            ),
            {"strategy_id": strategy_id, "symbol": symbol},
        )
        row = existing.mappings().first()
        signed_qty = qty if side in {"buy", "long"} else (-1 * qty)
        if row is None:
            await session.execute(
                text(
                    "INSERT INTO positions (symbol, side, qty, entry_price, current_price, unrealised_pnl, strategy_id) VALUES (:symbol, :side, :qty, :entry_price, :current_price, :unrealised_pnl, :strategy_id)"
                ),
                {
                    "symbol": symbol,
                    "side": "long" if signed_qty >= 0 else "short",
                    "qty": abs(signed_qty),
                    "entry_price": fill_price,
                    "current_price": fill_price,
                    "unrealised_pnl": 0.0,
                    "strategy_id": strategy_id,
                },
            )
            return
        existing_side = str(row["side"]).lower()
        existing_qty = float(row["qty"])
        existing_signed_qty = (
            existing_qty if existing_side in {"long", "buy"} else (-1 * existing_qty)
        )
        new_qty = existing_signed_qty + signed_qty
        next_side = (
            "flat" if abs(new_qty) < 1e-9 else ("long" if new_qty > 0 else "short")
        )
        await session.execute(
            text(
                "UPDATE positions SET side = :side, qty = :qty, current_price = :current_price WHERE id = :position_id"
            ),
            {
                "side": next_side,
                "qty": abs(new_qty),
                "current_price": fill_price,
                "position_id": row["id"],
            },
        )

    async def _insert_audit_log(
        self, session, event_type: str, payload: dict[str, Any]
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO audit_log (event_type, payload) VALUES (:event_type, CAST(:payload AS JSONB))"
            ),
            {"event_type": event_type, "payload": json.dumps(payload, default=str)},
        )
