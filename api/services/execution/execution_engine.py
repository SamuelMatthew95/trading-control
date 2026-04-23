"""Order execution engine backed by the paper broker.

Architecture note: ExecutionEngine is the SOLE authority for BUY/SELL orders.
It consumes advisory decisions from STREAM_DECISIONS (published by ReasoningAgent),
applies a weighted execution gate, checks the market clock, and only then
submits the order to the broker.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_EXECUTION,
    EXECUTION_DECISION_THRESHOLD,
    LARGE_ORDER_THRESHOLD,
    NO_ORDER_ACTIONS,
    ORDER_DEDUP_TTL_SECONDS,
    ORDER_LOCK_TTL_SECONDS,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_ORDER_DEDUP,
    REDIS_KEY_ORDER_LOCK,
    SOURCE_EXECUTION,
    STREAM_DECISIONS,
    STREAM_EXECUTIONS,
    STREAM_TRADE_LIFECYCLE,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    OrderSide,
    OrderStatus,
    PositionSide,
)
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
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
            bus,
            dlq,
            stream=STREAM_DECISIONS,
            group=DEFAULT_GROUP,
            consumer="execution-engine",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self.broker = broker
        self.agent_state = agent_state

    async def process(self, data: dict[str, Any]) -> None:
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")
        if not is_db_available():
            await self._process_in_memory(data)
            return

        # Validate required fields before any DB/broker interaction
        # Accepts both "action" (from STREAM_DECISIONS) and "side" (backward compat)
        side_or_action = str(data.get(FieldName.ACTION) or data.get(FieldName.SIDE) or "").lower()
        missing = [f for f in (FieldName.SYMBOL, FieldName.QTY, FieldName.PRICE) if not data.get(f)]
        if not side_or_action:
            missing.append("action/side")
        if missing:
            log_structured("warning", "order_missing_required_fields", missing=missing)
            return

        # strategy_id is required by the DB; fall back to a generated UUID if absent
        strategy_id = str(data.get(FieldName.STRATEGY_ID) or uuid.uuid4())
        symbol = str(data[FieldName.SYMBOL])
        side = side_or_action
        try:
            base_qty = float(data[FieldName.QTY])
            price = float(data[FieldName.PRICE])

            # Implement position sizing based on confidence and volatility
            try:
                confidence = float(
                    data.get(FieldName.CONFIDENCE) or data.get(FieldName.COMPOSITE_SCORE) or 0.5
                )
                volatility_factor = (
                    abs(float(data.get(FieldName.PCT, 0))) / 100.0
                )  # Convert percentage to decimal

                # Validate inputs
                if not (0.0 <= confidence <= 1.0):
                    log_structured(
                        "warning",
                        "position_sizing_invalid_confidence",
                        confidence=confidence,
                        symbol=symbol,
                    )
                    qty_multiplier = 1.0  # Default to minimum
                elif not (0.0 <= volatility_factor <= 1.0):
                    log_structured(
                        "warning",
                        "position_sizing_invalid_volatility",
                        volatility_factor=volatility_factor,
                        symbol=symbol,
                    )
                    qty_multiplier = 1.0  # Default to minimum
                else:
                    # Position sizing logic: vary qty between 1-3 based on confidence and volatility
                    if confidence > 0.7 and volatility_factor < 0.02:
                        qty_multiplier = 3.0  # High confidence, low volatility -> larger position
                    elif confidence > 0.5 and volatility_factor < 0.03:
                        qty_multiplier = (
                            2.0  # Medium confidence, moderate volatility -> medium position
                        )
                    else:
                        qty_multiplier = (
                            1.0  # Low confidence or high volatility -> minimum position
                        )

                qty = round(base_qty * qty_multiplier, 2)
                qty = max(1.0, qty)  # Ensure minimum quantity of 1

                # Final validation
                if not (0.1 <= qty <= 1000.0):  # Reasonable bounds
                    log_structured(
                        "warning", "position_sizing_out_of_bounds", qty=qty, symbol=symbol
                    )
                    qty = max(1.0, min(1000.0, qty))  # Clamp to reasonable range

            except (ValueError, TypeError) as e:
                log_structured(
                    "error",
                    "position_sizing_calculation_failed",
                    error=str(e),
                    symbol=symbol,
                    exc_info=True,
                )
                qty = max(1.0, base_qty)  # Fallback to base quantity with minimum

            log_structured(
                "info",
                "position_sizing_applied",
                symbol=symbol,
                base_qty=base_qty,
                confidence=confidence,
                volatility_factor=volatility_factor,
                qty_multiplier=qty_multiplier,
                final_qty=qty,
            )
        except (TypeError, ValueError):
            log_structured("warning", "order_invalid_numeric_fields", symbol=symbol)
            return
        # Reject non-positive quantity / price to prevent broker-side errors and
        # accidental zero-size orders slipping past the gate.
        if qty <= 0 or price <= 0:
            log_structured(
                "warning",
                "order_non_positive_numeric_fields",
                symbol=symbol,
                qty=qty,
                price=price,
            )
            return
        trace_id = str(data.get(FieldName.TRACE_ID) or uuid.uuid4())

        # --- Execution gate 1: skip non-order actions (hold, reject, flat) ----
        if side in NO_ORDER_ACTIONS:
            log_structured(
                "info",
                "execution_skipped_advisory_action",
                symbol=symbol,
                action=side,
                trace_id=trace_id,
            )
            return

        # --- Execution gate 2: weighted decision score -----------------------
        # final_score = signal_confidence * 0.50 + reasoning_score * 0.30 + perf * 0.20
        signal_confidence = float(
            data.get(FieldName.SIGNAL_CONFIDENCE)
            or data.get(FieldName.COMPOSITE_SCORE)
            or data.get(FieldName.CONFIDENCE)
            or 0.5
        )
        # Use reasoning_score if present; fall back to signal_confidence so
        # legacy test payloads (no reasoning_score field) still clear the gate.
        reasoning_score = float(data.get(FieldName.REASONING_SCORE) or signal_confidence)
        final_score = self._compute_final_score(signal_confidence, reasoning_score)
        threshold = (
            0.45
            if (settings.BROKER_MODE.lower() == "paper" or settings.ALPACA_PAPER)
            else EXECUTION_DECISION_THRESHOLD
        )
        if final_score < threshold:
            log_structured(
                "info",
                "execution_gated_score_below_threshold",
                symbol=symbol,
                final_score=round(final_score, 4),
                threshold=threshold,
                trace_id=trace_id,
            )
            return

        # --- Execution gate 3: market clock (equities only) ------------------
        if not self._is_market_open(symbol):
            log_structured(
                "info",
                "execution_blocked_market_closed",
                symbol=symbol,
                trace_id=trace_id,
            )
            return
        order_timestamp = self._parse_timestamp(data.get(FieldName.TIMESTAMP))
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
                    order_id=str(existing_row["id"]),  # SQLAlchemy Row mapping key
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
                fill_price = float(broker_result[FieldName.FILL_PRICE])

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
                        "status": broker_result[FieldName.STATUS],
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

        # Compute PnL based on side and position state
        if side in (OrderSide.SELL, PositionSide.SHORT):
            # SELL fills: calculate realized PnL when closing positions
            realized_pnl = self._compute_realized_pnl(prior_position, side, qty, fill_price)
        else:
            # BUY fills: calculate unrealized PnL if we have an existing position, otherwise null
            realized_pnl = self._compute_unrealized_pnl(prior_position, side, qty, fill_price)

        entry_price = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)

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
        pnl_percent = self._compute_pnl_percent(
            prior_position, side, qty, entry_price, realized_pnl
        )
        # SafeWriter.write_trade_performance requires trade_id, quantity,
        # entry_time, and schema_version (v3). Without these the persist layer
        # raises, the pipeline swallows it as best-effort, and the row never
        # lands -> trade_performance table stays empty -> PnL shows as zero.
        filled_at_iso = filled_at.isoformat()
        await self.bus.publish(
            STREAM_TRADE_PERFORMANCE,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.TYPE: "trade_performance",
                FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
                FieldName.ORDER_ID: order_id,
                FieldName.TRADE_ID: order_id,
                FieldName.STRATEGY_ID: strategy_id,
                FieldName.SYMBOL: symbol,
                FieldName.SIDE: side,
                FieldName.QTY: qty,
                FieldName.QUANTITY: qty,
                FieldName.FILL_PRICE: fill_price,
                FieldName.ENTRY_PRICE: entry_price,
                FieldName.EXIT_PRICE: fill_price,
                FieldName.PNL: realized_pnl,
                FieldName.PNL_PERCENT: pnl_percent,
                FieldName.TRACE_ID: trace_id,
                FieldName.FILLED_AT: filled_at_iso,
                FieldName.ENTRY_TIME: filled_at_iso,
                FieldName.EXIT_TIME: filled_at_iso,
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                FieldName.SOURCE: SOURCE_EXECUTION,
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
                status=OrderStatus.FILLED,
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

    async def _process_in_memory(self, data: dict[str, Any]) -> None:
        """Execute an order entirely in-memory when the DB is unavailable.

        Runs the same validation gates and broker call as the DB path, then
        writes the filled order and updated position to InMemoryStore so the
        dashboard fallback snapshot reflects real activity.
        """
        side_or_action = str(data.get(FieldName.ACTION) or data.get(FieldName.SIDE) or "").lower()
        missing = [f for f in (FieldName.SYMBOL, FieldName.QTY, FieldName.PRICE) if not data.get(f)]
        if not side_or_action:
            missing.append("action/side")
        if missing:
            log_structured("warning", "order_missing_required_fields_memory", missing=missing)
            return

        strategy_id = str(data.get(FieldName.STRATEGY_ID) or uuid.uuid4())
        symbol = str(data[FieldName.SYMBOL])
        side = side_or_action
        try:
            base_qty = float(data[FieldName.QTY])
            price = float(data[FieldName.PRICE])

            # Implement position sizing based on confidence and volatility (same as DB path)
            try:
                confidence = float(
                    data.get(FieldName.CONFIDENCE) or data.get(FieldName.COMPOSITE_SCORE) or 0.5
                )
                volatility_factor = abs(float(data.get(FieldName.PCT, 0))) / 100.0

                # Validate inputs
                if not (0.0 <= confidence <= 1.0):
                    log_structured(
                        "warning",
                        "position_sizing_invalid_confidence",
                        confidence=confidence,
                        symbol=symbol,
                    )
                    qty_multiplier = 1.0  # Default to minimum
                elif not (0.0 <= volatility_factor <= 1.0):
                    log_structured(
                        "warning",
                        "position_sizing_invalid_volatility",
                        volatility_factor=volatility_factor,
                        symbol=symbol,
                    )
                    qty_multiplier = 1.0  # Default to minimum
                else:
                    # Position sizing logic: vary qty between 1-3 based on confidence and volatility
                    if confidence > 0.7 and volatility_factor < 0.02:
                        qty_multiplier = 3.0
                    elif confidence > 0.5 and volatility_factor < 0.03:
                        qty_multiplier = 2.0
                    else:
                        qty_multiplier = 1.0

                qty = round(base_qty * qty_multiplier, 2)
                qty = max(1.0, qty)

                # Final validation
                if not (0.1 <= qty <= 1000.0):  # Reasonable bounds
                    log_structured(
                        "warning", "position_sizing_out_of_bounds", qty=qty, symbol=symbol
                    )
                    qty = max(1.0, min(1000.0, qty))  # Clamp to reasonable range

            except (ValueError, TypeError) as e:
                log_structured(
                    "error",
                    "position_sizing_calculation_failed",
                    error=str(e),
                    symbol=symbol,
                    exc_info=True,
                )
                qty = max(1.0, base_qty)  # Fallback to base quantity with minimum

            log_structured(
                "info",
                "position_sizing_applied_memory",
                symbol=symbol,
                base_qty=base_qty,
                confidence=confidence if "confidence" in locals() else 0.5,
                volatility_factor=volatility_factor if "volatility_factor" in locals() else 0.0,
                qty_multiplier=qty_multiplier if "qty_multiplier" in locals() else 1.0,
                final_qty=qty,
            )
        except (TypeError, ValueError):
            log_structured("warning", "order_invalid_numeric_fields_memory", symbol=symbol)
            return
        if qty <= 0 or price <= 0:
            log_structured(
                "warning",
                "order_non_positive_numeric_fields_memory",
                symbol=symbol,
                qty=qty,
                price=price,
            )
            return
        trace_id = str(data.get(FieldName.TRACE_ID) or uuid.uuid4())

        if side in NO_ORDER_ACTIONS:
            return

        signal_confidence = float(
            data.get(FieldName.SIGNAL_CONFIDENCE)
            or data.get(FieldName.COMPOSITE_SCORE)
            or data.get(FieldName.CONFIDENCE)
            or 0.5
        )
        reasoning_score = float(data.get(FieldName.REASONING_SCORE) or signal_confidence)
        final_score = self._compute_final_score(signal_confidence, reasoning_score)
        threshold = (
            0.45
            if (settings.BROKER_MODE.lower() == "paper" or settings.ALPACA_PAPER)
            else EXECUTION_DECISION_THRESHOLD
        )
        if final_score < threshold:
            return

        if not self._is_market_open(symbol):
            return

        # --- Idempotency guard (mirrors the DB-path SELECT on idempotency_key) ---
        # BaseStreamConsumer is at-least-once; redelivered messages must not
        # produce duplicate fills. Use Redis SET NX with a 24-hour TTL so any
        # realistic replay window is covered even when DB is unavailable.
        order_timestamp = self._parse_timestamp(data.get(FieldName.TIMESTAMP))
        idempotency_key = self._build_idempotency_key(
            strategy_id, symbol, side, order_timestamp, data
        )
        dedup_key = REDIS_KEY_ORDER_DEDUP.format(idempotency_key=idempotency_key)
        is_new = await self.redis.set(dedup_key, "1", ex=ORDER_DEDUP_TTL_SECONDS, nx=True)
        if not is_new:
            log_structured(
                "info",
                "memory_order_duplicate_skipped",
                idempotency_key=idempotency_key,
                symbol=symbol,
                trace_id=trace_id,
            )
            return

        order_id = str(uuid.uuid4())
        vwap_plan = self._build_vwap_plan(qty)
        lock_key = REDIS_KEY_ORDER_LOCK.format(symbol=symbol)
        lock_value = str(uuid.uuid4())

        prior_position = await self.broker.get_position(symbol)

        lock_acquired = await self.redis.set(
            lock_key, lock_value, ex=ORDER_LOCK_TTL_SECONDS, nx=True
        )
        if not lock_acquired:
            raise RuntimeError(f"Order lock already held for {symbol}")

        try:
            broker_result = await self.broker.place_order(symbol, side, qty, price)
            fill_price = float(broker_result[FieldName.FILL_PRICE])
            filled_at = datetime.now(timezone.utc)

            # Compute PnL based on side and position state (same logic as DB mode)
            if side in (OrderSide.SELL, PositionSide.SHORT):
                # SELL fills: calculate realized PnL when closing positions
                realized_pnl = self._compute_realized_pnl(prior_position, side, qty, fill_price)
            else:
                # BUY fills: calculate unrealized PnL if we have an existing position, otherwise null
                realized_pnl = self._compute_unrealized_pnl(prior_position, side, qty, fill_price)

            entry_price = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
            pnl_percent = self._compute_pnl_percent(
                prior_position, side, qty, entry_price, realized_pnl
            )

            store = get_runtime_store()
            store.add_order(
                {
                    "order_id": order_id,
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "quantity": qty,
                    "price": fill_price,
                    "filled_price": fill_price,
                    "status": broker_result[FieldName.STATUS],
                    "broker_order_id": broker_result["broker_order_id"],
                    "pnl": realized_pnl,
                    "pnl_percent": pnl_percent,
                    "filled_at": filled_at.isoformat(),
                    "trace_id": trace_id,
                }
            )
            # Surface on the dashboard trade_feed panel even when DB is down.
            store.upsert_trade_fill(
                {
                    "id": trace_id,
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
                }
            )

            # Update position in InMemoryStore
            signed_qty = qty if side in {OrderSide.BUY, PositionSide.LONG} else (-1 * qty)
            existing_pos = store.positions.get(symbol, {})
            existing_signed = float(existing_pos.get(FieldName.QTY, 0)) * (
                1
                if str(existing_pos.get(FieldName.SIDE, PositionSide.LONG)).lower()
                in {PositionSide.LONG, OrderSide.BUY}
                else -1
            )
            new_signed = existing_signed + signed_qty
            new_abs_qty = abs(new_signed)
            new_side = (
                PositionSide.FLAT
                if new_abs_qty < 1e-9
                else (PositionSide.LONG if new_signed > 0 else PositionSide.SHORT)
            )
            store.upsert_position(
                symbol,
                {
                    "symbol": symbol,
                    "side": new_side,
                    "qty": new_abs_qty,
                    "quantity": new_abs_qty,
                    "entry_price": entry_price,
                    "avg_cost": entry_price,
                    "current_price": fill_price,
                    "last_price": fill_price,
                    "market_value": round(new_abs_qty * fill_price, 8),
                    "unrealized_pnl": 0.0,
                    "strategy_id": strategy_id,
                },
            )

            # Publish stream events (same as DB path)
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
                "confidence": signal_confidence,
                "filled_at": filled_at.isoformat(),
                "trace_id": trace_id,
                "vwap_plan": vwap_plan,
                "source": SOURCE_EXECUTION,
            }
            await self.bus.publish(STREAM_EXECUTIONS, execution_payload)
            # Mirror of the DB-mode payload so the in-memory path also
            # satisfies SafeWriter.write_trade_performance if the pipeline
            # persists it once DB availability returns.
            filled_at_iso = filled_at.isoformat()
            await self.bus.publish(
                STREAM_TRADE_PERFORMANCE,
                {
                    FieldName.MSG_ID: str(uuid.uuid4()),
                    FieldName.TYPE: "trade_performance",
                    FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
                    FieldName.ORDER_ID: order_id,
                    FieldName.TRADE_ID: order_id,
                    FieldName.STRATEGY_ID: strategy_id,
                    FieldName.SYMBOL: symbol,
                    FieldName.SIDE: side,
                    FieldName.QTY: qty,
                    FieldName.QUANTITY: qty,
                    FieldName.FILL_PRICE: fill_price,
                    FieldName.ENTRY_PRICE: entry_price,
                    FieldName.EXIT_PRICE: fill_price,
                    FieldName.PNL: realized_pnl,
                    FieldName.PNL_PERCENT: pnl_percent,
                    FieldName.TRACE_ID: trace_id,
                    FieldName.FILLED_AT: filled_at_iso,
                    FieldName.ENTRY_TIME: filled_at_iso,
                    FieldName.EXIT_TIME: filled_at_iso,
                    FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                    FieldName.SOURCE: SOURCE_EXECUTION,
                },
            )
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
            log_structured(
                "info",
                "order_executed_memory",
                order_id=order_id,
                symbol=symbol,
                side=side,
                fill_price=fill_price,
                realized_pnl=realized_pnl,
                trace_id=trace_id,
            )
        finally:
            await self.redis.delete(lock_key)

        if self.agent_state:
            self.agent_state.record_event(_STATE_NAME, task=f"order_filled_memory:{symbol}")

        try:
            await _write_heartbeat(
                self.redis,
                _STATE_NAME,
                f"order_filled_memory:{symbol} side={side} fill_price={fill_price}",
            )
        except Exception:
            log_structured("warning", "execution_heartbeat_failed_memory", exc_info=True)

    def _compute_pnl_percent(
        self,
        prior_position: dict[str, Any],
        side: str,
        qty: float,
        entry_price: float,
        realized_pnl: float | None,
    ) -> float:
        """Return percentage return on the closed position's cost basis.

        Uses actual closed_qty (not order qty) so oversell scenarios don't
        inflate the denominator and produce an artificially small percentage.
        Returns 0.0 for null P&L (unrealized BUY fills).
        """
        if entry_price <= 0 or realized_pnl is None or realized_pnl == 0.0:
            return 0.0
        prior_qty = float(prior_position.get(FieldName.QTY) or 0)
        closed_qty = min(qty, prior_qty) if prior_qty > 0 else qty
        cost_basis = entry_price * (closed_qty if closed_qty > 0 else qty)
        return (realized_pnl / cost_basis) * 100 if cost_basis > 0 else 0.0

    def _compute_realized_pnl(
        self,
        prior_position: dict[str, Any],
        side: str,
        qty: float,
        fill_price: float,
    ) -> float:
        """Compute realized PnL when closing or partially closing a position."""
        prior_side = str(prior_position.get(FieldName.SIDE) or PositionSide.FLAT).lower()
        prior_entry = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
        prior_qty = float(prior_position.get(FieldName.QTY) or 0)

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

        # Opening or adding to a position — return null for BUY fills (unrealized)
        return None

    def _compute_unrealized_pnl(
        self,
        prior_position: dict[str, Any],
        side: str,
        qty: float,
        fill_price: float,
    ) -> float | None:
        """Compute unrealized PnL for BUY fills when opening or adding to positions.

        Returns null if no position exists, or calculated unrealized PnL if position exists.
        """
        prior_qty = float(prior_position.get(FieldName.QTY) or 0)

        # If we have an existing position, calculate unrealized PnL
        if prior_qty > 0:
            prior_entry = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
            if side in (OrderSide.BUY, PositionSide.LONG):
                # Adding to long position - calculate unrealized PnL on existing qty
                return round((fill_price - prior_entry) * prior_qty, 8)
            if side in (OrderSide.SELL, PositionSide.SHORT):
                # Adding to short position - calculate unrealized PnL on existing qty
                return round((prior_entry - fill_price) * prior_qty, 8)

        # No existing position - return null (unrealized)
        return None

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
                    "composite_score": signal_data.get(FieldName.COMPOSITE_SCORE),
                    "signal_type": signal_data.get(FieldName.SIGNAL_TYPE),
                    FieldName.PRICE: signal_data.get(FieldName.PRICE),
                    FieldName.QTY: signal_data.get(FieldName.QTY),
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

    def _compute_final_score(
        self,
        signal_confidence: float,
        reasoning_score: float,
        historical_perf: float = 0.5,
    ) -> float:
        """Weighted execution score used as a gate before submitting orders.

        Weights: signal 50%, reasoning 30%, historical performance 20%.
        ``historical_perf`` defaults to 0.5 (neutral) when unavailable.
        """
        return (signal_confidence * 0.50) + (reasoning_score * 0.30) + (historical_perf * 0.20)

    def _is_market_open(self, symbol: str) -> bool:
        """Return True if trading is currently allowed for this symbol.

        Crypto assets (symbols containing '/') trade 24/7.
        Equities are restricted to regular US market hours: 9:30–16:00 ET, Mon–Fri.
        Falls back to True on any error so the gate never silently blocks crypto.
        """
        if settings.BROKER_MODE.lower() == "paper" or settings.ALPACA_PAPER:
            return True
        if "/" in symbol:
            return True  # Crypto: BTC/USD, ETH/USD, SOL/USD — always open

        try:
            from zoneinfo import ZoneInfo

            et_tz = ZoneInfo("America/New_York")
            now_et = datetime.now(et_tz)
            if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
                return False
            market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            return market_open <= now_et < market_close
        except Exception:
            log_structured("warning", "market_clock_check_failed", exc_info=True)
            return True  # Fail open — never silently block a valid order

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
        existing_side = str(row[FieldName.SIDE]).lower()
        existing_qty = float(row[FieldName.QTY])
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
