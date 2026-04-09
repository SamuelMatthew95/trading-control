"""Order execution engine backed by the paper broker."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.constants import (
    AGENT_EXECUTION,
    LARGE_ORDER_THRESHOLD,
    ORDER_LOCK_TTL_SECONDS,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_ORDER_LOCK,
    SOURCE_EXECUTION,
    STREAM_EXECUTIONS,
    STREAM_ORDERS,
    STREAM_TRADE_LIFECYCLE,
    STREAM_TRADE_PERFORMANCE,
    OrderSide,
    OrderStatus,
    PositionSide,
)
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.execution.brokers.paper import PaperBroker

_STATE_NAME = AGENT_EXECUTION  # single source of truth from constants


class ExecutionEngine(BaseStreamConsumer):
    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        broker: PaperBroker,
        *,
        agent_state: AgentStateRegistry | None = None,
    ):
        super().__init__(
            bus, dlq, stream=STREAM_ORDERS, group=DEFAULT_GROUP, consumer="execution-engine"
        )
        self.redis = redis_client
        self.broker = broker
        self.agent_state = agent_state

    async def process(self, data: dict[str, Any]) -> None:
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")

        # Validate required fields before any DB/broker interaction
        missing = [f for f in ("symbol", "side", "qty", "price") if not data.get(f)]
        if missing:
            log_structured("warning", "order_missing_required_fields", missing=missing)
            return

        # strategy_id is required by the DB; fall back to a generated UUID if absent
        strategy_id = str(data.get("strategy_id") or uuid.uuid4())
        symbol = str(data["symbol"])
        side = str(data["side"]).lower()
        try:
            qty = float(data["qty"])
            price = float(data["price"])
        except (TypeError, ValueError):
            log_structured("warning", "order_invalid_numeric_fields", symbol=symbol)
            return
        trace_id = str(data.get("trace_id") or uuid.uuid4())
        order_timestamp = self._parse_timestamp(data.get("timestamp"))
        idempotency_key = self._build_idempotency_key(
            strategy_id, symbol, side, order_timestamp, data
        )
        lock_key = REDIS_KEY_ORDER_LOCK.format(symbol=symbol)
        lock_value = str(uuid.uuid4())

        # Snapshot position BEFORE order to compute realized PnL
        prior_position = await self.broker.get_position(symbol)

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

            lock_acquired = await self.redis.set(
                lock_key, lock_value, ex=ORDER_LOCK_TTL_SECONDS, nx=True
            )
            if not lock_acquired:
                raise RuntimeError(f"Order lock already held for {symbol}")

            order_id: str | None = None
            vwap_plan = self._build_vwap_plan(qty)
            try:
                inserted = await session.execute(
                    text(
                        # Dual-write old (qty) + new (quantity) column names so both
                        # raw-SQL agents and ORM-based MetricsAggregator see real values.
                        "INSERT INTO orders "
                        "(strategy_id, symbol, side, qty, quantity, price, status, "
                        " idempotency_key, broker_order_id, source, schema_version) "
                        "VALUES (:strategy_id, :symbol, :side, :qty, :qty, :price, :status, "
                        "        :idempotency_key, NULL, :source, :schema_version) "
                        "RETURNING id"
                    ),
                    {
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "idempotency_key": idempotency_key,
                        "status": OrderStatus.PENDING,
                        "source": SOURCE_EXECUTION,
                        "schema_version": DB_SCHEMA_VERSION,
                    },
                )
                order_id = str(inserted.scalar_one())
                await session.flush()

                broker_result = await self.broker.place_order(symbol, side, qty, price)
                filled_at = datetime.now(timezone.utc).replace(tzinfo=None)
                fill_price = float(broker_result["fill_price"])

                await session.execute(
                    text(
                        # Also set filled_price / filled_quantity (ORM column names) so
                        # MetricsAggregator snapshot shows non-null fill data.
                        "UPDATE orders SET "
                        "  status = :status, "
                        "  broker_order_id = :broker_order_id, "
                        "  price = :fill_price, "
                        "  filled_price = :fill_price, "
                        "  filled_quantity = :qty, "
                        "  filled_at = :filled_at "
                        "WHERE id = :order_id"
                    ),
                    {
                        "status": broker_result["status"],
                        "broker_order_id": broker_result["broker_order_id"],
                        "fill_price": fill_price,
                        "qty": qty,
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
                    fill_price=fill_price,
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

        # Compute realized PnL from prior position snapshot
        realized_pnl = self._compute_realized_pnl(prior_position, side, qty, fill_price)
        entry_price = float(prior_position.get("entry_price") or fill_price)

        # Retrieve the agent's confidence from agent_runs so GradeAgent gets a real value
        confidence = 0.5
        try:
            async with AsyncSessionFactory() as _conf_session:
                _conf_result = await _conf_session.execute(
                    text("SELECT confidence FROM agent_runs WHERE trace_id = :tid LIMIT 1"),
                    {"tid": trace_id},
                )
                _conf_val = _conf_result.scalar()
                if _conf_val is not None:
                    confidence = float(_conf_val)
        except Exception:
            pass  # Fall back to 0.5; best-effort only

        execution_payload: dict[str, Any] = {
            "type": "order_filled",
            "msg_id": str(uuid.uuid4()),
            "order_id": order_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "fill_price": fill_price,
            "confidence": confidence,
            "filled_at": filled_at.isoformat(),
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "vwap_plan": vwap_plan,
            "source": SOURCE_EXECUTION,
        }
        await self.bus.publish(STREAM_EXECUTIONS, execution_payload)

        # Publish to trade_performance stream so GradeAgent / ICUpdater / ReflectionAgent
        # have real fill data with realized PnL to work with
        pnl_percent = (realized_pnl / (entry_price * qty)) * 100 if entry_price * qty > 0 else 0.0
        await self.bus.publish(
            STREAM_TRADE_PERFORMANCE,
            {
                "msg_id": str(uuid.uuid4()),
                "type": "trade_performance",
                "order_id": order_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "fill_price": fill_price,
                "entry_price": entry_price,
                "exit_price": fill_price,
                "pnl": realized_pnl,
                "pnl_percent": pnl_percent,
                "trace_id": trace_id,
                "filled_at": filled_at.isoformat(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": SOURCE_EXECUTION,
            },
        )
        log_structured(
            "info",
            "order_executed",
            order_id=order_id,
            symbol=symbol,
            side=side,
            fill_price=fill_price,
            realized_pnl=realized_pnl,
            trace_id=trace_id,
        )

        # Persist end-to-end trade lifecycle row (best-effort, never raises)
        try:
            from api.services.agents.db_helpers import upsert_trade_lifecycle

            await upsert_trade_lifecycle(
                execution_trace_id=trace_id,
                symbol=symbol,
                side=side,
                qty=qty,
                entry_price=entry_price,
                exit_price=fill_price,
                pnl=realized_pnl,
                pnl_percent=pnl_percent,
                order_id=order_id,
                status="filled",
                filled_at=filled_at.isoformat(),
            )
        except Exception:
            log_structured(
                "warning", "trade_lifecycle_write_failed", trace_id=trace_id, exc_info=True
            )

        # Broadcast fill to dashboard WS so trade feed updates live
        await self.bus.publish(
            STREAM_TRADE_LIFECYCLE,
            {
                "type": "trade_filled",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": fill_price,
                "pnl": realized_pnl,
                "pnl_percent": pnl_percent,
                "order_id": order_id,
                "execution_trace_id": trace_id,
                "status": OrderStatus.FILLED,
                "filled_at": filled_at.isoformat(),
                "timestamp": filled_at.isoformat(),
                "source": SOURCE_EXECUTION,
            },
        )

        if self.agent_state:
            self.agent_state.record_event(_STATE_NAME, task=f"order_filled:{symbol}")

        # Write Redis + Postgres heartbeat so dashboard shows EXECUTION_ENGINE as ACTIVE
        try:
            await _write_heartbeat(
                self.redis,
                _STATE_NAME,
                f"order_filled:{symbol} side={side} fill_price={fill_price}",
            )
        except Exception:
            log_structured("warning", "execution_heartbeat_failed", exc_info=True)

    def _compute_realized_pnl(
        self,
        prior_position: dict[str, Any],
        side: str,
        qty: float,
        fill_price: float,
    ) -> float:
        """Compute realized PnL when closing or partially closing a position."""
        prior_side = str(prior_position.get("side") or PositionSide.FLAT).lower()
        prior_entry = float(prior_position.get("entry_price") or fill_price)
        prior_qty = float(prior_position.get("qty") or 0)

        # Closing a long position with a sell
        if (
            prior_side == PositionSide.LONG
            and side in (OrderSide.SELL, PositionSide.SHORT)
            and prior_qty > 0
        ):
            closed_qty = min(qty, prior_qty)
            return round((fill_price - prior_entry) * closed_qty, 8)

        # Closing a short position with a buy
        if (
            prior_side == PositionSide.SHORT
            and side in (OrderSide.BUY, PositionSide.LONG)
            and prior_qty > 0
        ):
            closed_qty = min(qty, prior_qty)
            return round((prior_entry - fill_price) * closed_qty, 8)

        # Opening or adding to a position — no realized PnL yet
        return 0.0

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
        # Python 3.10 fromisoformat does not accept the 'Z' suffix; normalise first.
        s = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(s)
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
        signed_qty = qty if side in {OrderSide.BUY, PositionSide.LONG} else (-1 * qty)
        if row is None:
            pos_qty = abs(signed_qty)
            pos_side = PositionSide.LONG if signed_qty >= 0 else PositionSide.SHORT
            market_value = round(pos_qty * fill_price, 8)
            await session.execute(
                text(
                    # Dual-write old (qty/entry_price/current_price/unrealised_pnl) +
                    # new (quantity/avg_cost/last_price/market_value/unrealized_pnl)
                    # column names so MetricsAggregator ORM queries return real values.
                    "INSERT INTO positions "
                    "(symbol, side, qty, quantity, entry_price, avg_cost, "
                    " current_price, last_price, market_value, "
                    " unrealised_pnl, unrealized_pnl, strategy_id,"
                    " schema_version, source) "
                    "VALUES (:symbol, :side, :qty, :qty, :entry_price, :entry_price, "
                    "        :current_price, :current_price, :market_value, "
                    "        0.0, 0.0, :strategy_id, :schema_version, :source)"
                ),
                {
                    "symbol": symbol,
                    "side": pos_side,
                    "qty": pos_qty,
                    "entry_price": fill_price,
                    "current_price": fill_price,
                    "market_value": market_value,
                    "strategy_id": strategy_id,
                    "schema_version": DB_SCHEMA_VERSION,
                    "source": SOURCE_EXECUTION,
                },
            )
            return
        existing_side = str(row["side"]).lower()
        existing_qty = float(row["qty"])
        existing_signed_qty = (
            existing_qty
            if existing_side in {PositionSide.LONG, OrderSide.BUY}
            else (-1 * existing_qty)
        )
        new_qty = existing_signed_qty + signed_qty
        next_side = (
            PositionSide.FLAT
            if abs(new_qty) < 1e-9
            else (PositionSide.LONG if new_qty > 0 else PositionSide.SHORT)
        )
        new_abs_qty = abs(new_qty)
        new_market_value = round(new_abs_qty * fill_price, 8)
        await session.execute(
            text(
                # Keep old (qty/current_price) and new (quantity/last_price/market_value)
                # column names in sync so MetricsAggregator ORM queries return real values.
                "UPDATE positions SET side = :side, qty = :qty, quantity = :qty,"
                " current_price = :current_price, last_price = :current_price,"
                " market_value = :market_value WHERE id = :position_id"
            ),
            {
                "side": next_side,
                "qty": new_abs_qty,
                "current_price": fill_price,
                "market_value": new_market_value,
                "position_id": row["id"],
            },
        )

    async def _insert_audit_log(self, session, event_type: str, payload: dict[str, Any]) -> None:
        await session.execute(
            text(
                "INSERT INTO audit_log (event_type, payload) VALUES (:event_type, CAST(:payload AS JSONB))"
            ),
            {"event_type": event_type, "payload": json.dumps(payload, default=str)},
        )
