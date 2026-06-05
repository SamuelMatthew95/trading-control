"""Order execution engine backed by the paper broker.

Architecture note: ExecutionEngine is the SOLE authority for BUY/SELL orders.
It consumes advisory decisions from STREAM_DECISIONS (published by ReasoningAgent),
applies a weighted execution gate, checks the market clock, and only then
submits the order to the broker.

Sub-modules (pure, no IO):
  decision_utils  — decision validation and gate scoring
  position_math   — position state and PnL calculations
  fill_publisher  — stream event publishing (FillContext + publish_fill_events)
  order_writer    — DB INSERT/UPDATE for orders, positions, audit_log
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_EXECUTION,
    COOLING_OFF_DECAY,
    COOLING_OFF_WINDOW,
    EXECUTION_DECISION_THRESHOLD,
    EXECUTION_DECISION_THRESHOLD_MEMORY,
    IN_FLIGHT_TTL_SECONDS,
    LARGE_ORDER_THRESHOLD,
    NO_ORDER_ACTIONS,
    ORDER_DEDUP_TTL_SECONDS,
    ORDER_LOCK_TTL_SECONDS,
    REDIS_KEY_IN_FLIGHT_ORDER,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_ORDER_DEDUP,
    REDIS_KEY_ORDER_LOCK,
    REDIS_KEY_RECENT_OUTCOMES,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    REDIS_RECENT_OUTCOMES_MAXLEN,
    SIGNAL_CONFIDENCE_MIN_GATE,
    SLIPPAGE_PCT_PER_SIDE,
    SOURCE_EXECUTION,
    STREAM_DECISIONS,
    STREAM_SELL_REJECTED,
    TOOL_BRACKET_ORDER,
    TOOL_RISK_CAGE,
    TOOL_VWAP_EXECUTION,
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
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.decision_utils import (
    ParsedDecision as _ParsedDecision,
)
from api.services.execution.decision_utils import (
    check_confidence_gate,
    check_execution_gate,
    check_net_ev_gate,
    compute_execution_score,
    extract_decision_scores,
    parse_decision_fields,
)
from api.services.execution.fill_publisher import FillContext, publish_fill_events
from api.services.execution.order_writer import (
    insert_audit_log,
    insert_pending_order,
    insert_rejected_order_once,
    update_order_fill,
    upsert_position_db,
)
from api.services.execution.position_math import (
    clamp_buy_to_position_limit,
    compute_pnl_percent,
    compute_realized_pnl,
    is_round_trip_close,
    reject_unmatched_sell,
    signed_position_qty,
)
from api.services.market_status import get_market_status
from api.services.risk_filters import is_cooling_off
from api.services.tool_registry import get_tool_registry

_STATE_NAME = AGENT_EXECUTION  # single source of truth from constants


class ExecutionEngine(BaseStreamConsumer):
    _heartbeat_agent_name = AGENT_EXECUTION

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
        self._decisions_evaluated: int = 0  # total decisions received (holds + gated + executed)

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    async def process(self, data: dict[str, Any]) -> None:
        # Check kill switch BEFORE incrementing so that retried messages (which are
        # not acked when KillSwitchActive is raised) don't inflate the counter.
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")
        self._decisions_evaluated += 1

        # Learning-loop circuit breaker — set by ProposalApplier when GradeAgent
        # publishes a Grade F retirement proposal. Distinct from the manual
        # kill switch so the dashboard can distinguish "operator paused" from
        # "system paused itself because trades are losing".
        if await self.redis.get(REDIS_KEY_TRADING_PAUSED) == "1":
            reason = await self.redis.get(REDIS_KEY_TRADING_PAUSED_REASON) or "learning_loop_paused"
            symbol = str(data.get(FieldName.SYMBOL) or "?")
            trace_id = str(data.get(FieldName.TRACE_ID) or "")
            log_structured(
                "warning",
                "execution_blocked_trading_paused",
                symbol=symbol,
                reason=reason,
                trace_id=trace_id,
            )
            await self._write_idle_heartbeat(symbol, "blocked:trading_paused", trace_id)
            return

        if not is_db_available():
            await self._process_in_memory(data)
            return

        await self._process_with_db(data)

    # -------------------------------------------------------------------------
    # DB path
    # -------------------------------------------------------------------------

    async def _process_with_db(self, data: dict[str, Any]) -> None:
        parsed = await self._parse_and_validate(data)
        if parsed is None:
            return

        signal_confidence, reasoning_score = self._extract_scores(data)
        log_structured(
            "info",
            "execution_engine_decision_received",
            action=parsed.side,
            symbol=parsed.symbol,
            price=parsed.price,
            qty=parsed.qty,
            trace_id=parsed.trace_id,
        )
        _atr_raw = data.get(FieldName.ATR_REGIME_RATIO)
        _atr_regime_ratio = float(_atr_raw) if _atr_raw not in (None, "") else None
        _abs_pct_move = abs(float(data.get(FieldName.PCT) or 0.0))
        if await self._check_pre_execution_gates(
            parsed.side,
            parsed.symbol,
            signal_confidence,
            reasoning_score,
            parsed.trace_id,
            atr_regime_ratio=_atr_regime_ratio,
            abs_pct_move=_abs_pct_move,
        ):
            return

        symbol = parsed.symbol
        side = parsed.side
        qty = await self._apply_kelly_sizing(data, parsed.qty, parsed.price)
        price = parsed.price
        strategy_id = parsed.strategy_id
        trace_id = parsed.trace_id

        order_timestamp = self._parse_timestamp(data.get(FieldName.TIMESTAMP))
        idempotency_key = self._build_idempotency_key(
            strategy_id, symbol, side, order_timestamp, data
        )
        lock_key = REDIS_KEY_ORDER_LOCK.format(symbol=symbol)
        lock_value = str(uuid.uuid4())

        _db_exception: Exception | None = None
        _db_broker_result: dict[str, Any] | None = None
        async with AsyncSessionFactory() as session:
            existing = await session.execute(
                text("SELECT id, status FROM orders WHERE idempotency_key = :idempotency_key"),
                {"idempotency_key": idempotency_key},
            )
            if existing.mappings().first() is not None:
                log_structured(
                    "info",
                    "Skipping duplicate order event",
                    idempotency_key=idempotency_key,
                )
                return

            lock_acquired = await self.redis.set(
                lock_key, lock_value, ex=ORDER_LOCK_TTL_SECONDS, nx=True
            )
            if not lock_acquired:
                raise RuntimeError(f"Order lock already held for {symbol}")

            order_id: str | None = None
            vwap_plan: list[float] | None = None
            # Snapshot position AFTER acquiring the lock so concurrent orders
            # for the same symbol cannot race on a stale position read.
            prior_position = await self.broker.get_position(symbol)
            try:
                if reject_unmatched_sell(side=side, prior_position=prior_position):
                    log_structured(
                        "warning",
                        "execution_sell_rejected_no_open_position",
                        symbol=symbol,
                        trace_id=trace_id,
                    )
                    rejection_order_id, created = await insert_rejected_order_once(
                        session,
                        idempotency_key=idempotency_key,
                        strategy_id=strategy_id,
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        price=price,
                    )
                    await session.commit()
                    if not created:
                        log_structured(
                            "info",
                            "duplicate_sell_rejection_skipped",
                            symbol=symbol,
                            idempotency_key=idempotency_key,
                            trace_id=trace_id,
                        )
                        return
                    # Publish after commit so the rejection is durable before any
                    # downstream consumer sees the event.  Wrap in its own try so a
                    # transient bus failure never reaches the outer except/rollback
                    # handler — the rejection row is already committed and the early
                    # dedup SELECT will suppress any redelivery.
                    try:
                        await self.bus.publish(
                            STREAM_SELL_REJECTED,
                            {
                                FieldName.TYPE: "sell_rejected",
                                FieldName.REJECTION_REASON: "NO_OPEN_POSITION",
                                FieldName.SYMBOL: symbol,
                                FieldName.SIDE: side,
                                FieldName.QTY: qty,
                                FieldName.ORDER_ID: rejection_order_id,
                                FieldName.IDEMPOTENCY_KEY: idempotency_key,
                                FieldName.TRACE_ID: trace_id,
                                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                                FieldName.SOURCE: SOURCE_EXECUTION,
                            },
                        )
                    except Exception:
                        log_structured(
                            "warning",
                            "sell_rejected_event_publish_failed",
                            symbol=symbol,
                            idempotency_key=idempotency_key,
                            trace_id=trace_id,
                            exc_info=True,
                        )
                    return

                # Clamp oversell: never sell more than the open position holds.
                if side in (OrderSide.SELL, PositionSide.SHORT):
                    prior_qty = float(prior_position.get(FieldName.QTY) or 0)
                    if prior_qty > 0 and qty > prior_qty:
                        log_structured(
                            "warning",
                            "execution_sell_qty_clamped_to_available",
                            symbol=symbol,
                            requested_qty=qty,
                            available_qty=prior_qty,
                            trace_id=trace_id,
                        )
                        qty = prior_qty

                # Clamp overbuy: never let a BUY push the resulting long position
                # past the per-symbol exposure cap. The pre-trade size bound for
                # BUYs (mirrors the oversell clamp above) — without it a runaway or
                # hallucinated Kelly SIZE_PCT could open an unbounded position.
                if side in (OrderSide.BUY, PositionSide.LONG):
                    max_position = min(settings.MAX_SYMBOL_EXPOSURE, settings.MAX_OPEN_POSITION_QTY)
                    capped_qty = clamp_buy_to_position_limit(prior_position, qty, max_position)
                    if capped_qty <= 0:
                        log_structured(
                            "warning",
                            "execution_buy_rejected_position_limit",
                            symbol=symbol,
                            requested_qty=qty,
                            max_position_qty=max_position,
                            current_position_qty=signed_position_qty(prior_position),
                            trace_id=trace_id,
                        )
                        return
                    if capped_qty < qty:
                        log_structured(
                            "warning",
                            "execution_buy_qty_clamped_to_position_limit",
                            symbol=symbol,
                            requested_qty=qty,
                            clamped_qty=capped_qty,
                            max_position_qty=max_position,
                            trace_id=trace_id,
                        )
                        qty = capped_qty

                # Compute VWAP plan after oversell clamping so the slicing plan
                # reflects the actual executed quantity, not the requested qty.
                vwap_plan = self._build_vwap_plan(qty)
                order_id = await insert_pending_order(
                    session,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=price,
                    idempotency_key=idempotency_key,
                    status=OrderStatus.PENDING,
                )
                await session.flush()

                await self.redis.set(REDIS_KEY_IN_FLIGHT_ORDER, "1", ex=IN_FLIGHT_TTL_SECONDS)
                _bracket_t0 = time.monotonic()
                broker_result = await self.broker.place_order(symbol, side, qty, price)
                self._record_exec_tool(
                    TOOL_BRACKET_ORDER,
                    latency_ms=(time.monotonic() - _bracket_t0) * 1000,
                    success=True,
                )
                _db_broker_result = broker_result
                filled_at = datetime.now(timezone.utc).replace(tzinfo=None)
                fill_price = float(broker_result[FieldName.FILL_PRICE])

                await update_order_fill(
                    session,
                    order_id=order_id,
                    status=broker_result[FieldName.STATUS],
                    broker_order_id=broker_result[FieldName.BROKER_ORDER_ID],
                    fill_price=fill_price,
                    qty=qty,
                    filled_at=filled_at,
                )
                # The PaperBroker (Redis) is the position source of truth; pass
                # its authoritative post-fill entry so the DB row mirrors the
                # broker's weighted-average cost instead of drifting on adds.
                _db_broker_position = await self.broker.get_position(symbol)
                await upsert_position_db(
                    session,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    fill_price=fill_price,
                    avg_cost=float(_db_broker_position.get(FieldName.ENTRY_PRICE) or fill_price),
                )
                await insert_audit_log(
                    session,
                    event_type="order_placed",
                    payload={
                        FieldName.ORDER_ID: order_id,
                        FieldName.STRATEGY_ID: strategy_id,
                        FieldName.SYMBOL: symbol,
                        FieldName.SIDE: side,
                        FieldName.QTY: qty,
                        FieldName.BROKER_ORDER_ID: broker_result[FieldName.BROKER_ORDER_ID],
                        FieldName.VWAP_PLAN: vwap_plan,
                    },
                )
                await session.commit()
                # Record realized PnL for cooling-off gate (best-effort)
                _realized_pnl = compute_realized_pnl(prior_position, side, qty, fill_price)
                if _realized_pnl != 0.0:
                    try:
                        await self.redis.lpush(REDIS_KEY_RECENT_OUTCOMES, str(_realized_pnl))
                        await self.redis.ltrim(
                            REDIS_KEY_RECENT_OUTCOMES, 0, REDIS_RECENT_OUTCOMES_MAXLEN - 1
                        )
                    except Exception:
                        pass
                # Clear the in-flight flag now that the outcome is recorded
                try:
                    await self.redis.delete(REDIS_KEY_IN_FLIGHT_ORDER)
                except Exception:
                    pass
            except Exception as exc:
                await session.rollback()
                _db_exception = exc
            finally:
                await self.redis.delete(lock_key)

        if _db_exception is not None:
            await self._handle_db_failure(
                _db_exception,
                _db_broker_result,
                data=data,
                prior_position=prior_position,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                strategy_id=strategy_id,
                trace_id=trace_id,
                signal_confidence=signal_confidence,
                idempotency_key=idempotency_key,
                vwap_plan=vwap_plan,
            )
            return

        # Happy path: compute PnL and publish stream events
        realized_pnl = compute_realized_pnl(prior_position, side, qty, fill_price)
        entry_price = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
        is_close = is_round_trip_close(prior_position, side, qty)
        pnl_value = realized_pnl if is_close else None
        pnl_percent = compute_pnl_percent(prior_position, side, qty, entry_price, realized_pnl)

        # Retrieve confidence from agent_runs so GradeAgent gets a real value
        confidence = signal_confidence
        try:
            async with AsyncSessionFactory() as _s:
                _row = await _s.execute(
                    text("SELECT confidence FROM agent_runs WHERE trace_id = :tid LIMIT 1"),
                    {FieldName.TID: trace_id},
                )
                _val = _row.scalar()
                if _val is not None:
                    confidence = float(_val)
        except Exception:
            pass

        ctx = FillContext(
            order_id=order_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fill_price=fill_price,
            entry_price=entry_price,
            signal_confidence=confidence,
            pnl_value=pnl_value,
            pnl_percent=pnl_percent,
            realized_pnl=realized_pnl,
            is_round_trip_close=is_close,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            vwap_plan=vwap_plan,
            filled_at=datetime.now(timezone.utc),
            model_used=str(data.get(FieldName.MODEL_USED) or ""),
            primary_edge=str(data.get(FieldName.PRIMARY_EDGE) or ""),
            decision_cost_usd=float(data.get(FieldName.DECISION_COST_USD) or 0.0),
        )
        await publish_fill_events(self.bus, ctx)

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
            from api.services.agents.db_helpers import upsert_trade_lifecycle  # noqa: PLC0415

            await upsert_trade_lifecycle(
                execution_trace_id=trace_id,
                symbol=symbol,
                side=side,
                qty=qty,
                entry_price=entry_price,
                exit_price=fill_price if is_close else None,
                pnl=pnl_value,
                pnl_percent=pnl_percent,
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_at=ctx.filled_at.isoformat(),
                session_id=strategy_id,
            )
        except Exception:
            log_structured(
                "warning", "trade_lifecycle_write_failed", trace_id=trace_id, exc_info=True
            )

        if self.agent_state:
            self.agent_state.record_event(_STATE_NAME, task=f"order_filled:{symbol}")

        try:
            await _write_heartbeat(
                self.redis,
                _STATE_NAME,
                f"order_filled:{symbol} side={side} fill_price={fill_price}",
                self._decisions_evaluated,
            )
        except Exception:
            log_structured("warning", "execution_heartbeat_failed", exc_info=True)

    # -------------------------------------------------------------------------
    # DB failure fallback
    # -------------------------------------------------------------------------

    async def _handle_db_failure(
        self,
        exc: Exception,
        broker_result: dict[str, Any] | None,
        *,
        data: dict[str, Any],
        prior_position: dict[str, Any],
        symbol: str,
        side: str,
        qty: float,
        price: float,
        strategy_id: str,
        trace_id: str,
        signal_confidence: float,
        idempotency_key: str,
        vwap_plan: list[float] | None,
    ) -> None:
        try:
            raise exc
        except Exception:
            log_structured(
                "error",
                "execution_db_path_failed_using_memory_fallback",
                symbol=symbol,
                trace_id=trace_id,
                exc_info=True,
            )

        if broker_result is None:
            # Broker was never called; safe to run the full in-memory path.
            await self._process_in_memory(data)
            return

        # Broker already filled the order before the DB failure — record in memory
        # without re-submitting a second order.
        fill_price = float(broker_result[FieldName.FILL_PRICE])
        filled_at = datetime.now(timezone.utc)

        realized_pnl = compute_realized_pnl(prior_position, side, qty, fill_price)
        entry_price = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
        is_close = is_round_trip_close(prior_position, side, qty)
        pnl_value = realized_pnl if is_close else None
        pnl_percent = compute_pnl_percent(prior_position, side, qty, entry_price, realized_pnl)
        fallback_order_id = str(uuid.uuid4())

        # Record via the single in-memory fill path — the broker already filled
        # before the DB failure, so its position is authoritative and mirrored
        # into the store (no apply_decision, no recompute, no double-count).
        ctx = FillContext(
            order_id=fallback_order_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fill_price=fill_price,
            entry_price=entry_price,
            signal_confidence=signal_confidence,
            pnl_value=pnl_value,
            pnl_percent=pnl_percent,
            realized_pnl=realized_pnl,
            is_round_trip_close=is_close,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            vwap_plan=vwap_plan,
            filled_at=filled_at,
            model_used=str(data.get(FieldName.MODEL_USED) or ""),
            primary_edge=str(data.get(FieldName.PRIMARY_EDGE) or ""),
            decision_cost_usd=float(data.get(FieldName.DECISION_COST_USD) or 0.0),
        )
        await self._record_fill_to_store(
            ctx, broker_order_id=str(broker_result[FieldName.BROKER_ORDER_ID])
        )
        await publish_fill_events(self.bus, ctx)

        log_structured(
            "warning",
            "execution_db_fill_recorded_in_memory_no_resubmit",
            symbol=symbol,
            fill_price=fill_price,
            trace_id=trace_id,
        )
        try:
            await _write_heartbeat(
                self.redis,
                _STATE_NAME,
                f"db_fail_fill_recorded:{symbol}",
                self._decisions_evaluated,
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # In-memory path
    # -------------------------------------------------------------------------

    async def _process_in_memory(self, data: dict[str, Any]) -> None:
        """Execute an order entirely in-memory when the DB is unavailable.

        Runs the same validation gates and broker call as the DB path, then
        writes the filled order and updated position to InMemoryStore so the
        dashboard fallback snapshot reflects real activity.
        """
        parsed = await self._parse_and_validate(data)
        if parsed is None:
            return

        signal_confidence, reasoning_score = self._extract_scores(data)
        log_structured(
            "info",
            "execution_engine_decision_received",
            action=parsed.side,
            symbol=parsed.symbol,
            price=parsed.price,
            qty=parsed.qty,
            trace_id=parsed.trace_id,
        )
        _atr_raw2 = data.get(FieldName.ATR_REGIME_RATIO)
        _atr_regime_ratio2 = float(_atr_raw2) if _atr_raw2 not in (None, "") else None
        _abs_pct_move2 = abs(float(data.get(FieldName.PCT) or 0.0))
        if await self._check_pre_execution_gates(
            parsed.side,
            parsed.symbol,
            signal_confidence,
            reasoning_score,
            parsed.trace_id,
            atr_regime_ratio=_atr_regime_ratio2,
            abs_pct_move=_abs_pct_move2,
        ):
            return

        symbol = parsed.symbol
        side = parsed.side
        qty = await self._apply_kelly_sizing(data, parsed.qty, parsed.price)
        price = parsed.price
        strategy_id = parsed.strategy_id
        trace_id = parsed.trace_id

        # Idempotency guard — mirrors the DB-path SELECT on idempotency_key.
        # BaseStreamConsumer is at-least-once; redelivered messages must not
        # produce duplicate fills. Use Redis SET NX with a 24-hour TTL.
        order_timestamp = self._parse_timestamp(data.get(FieldName.TIMESTAMP))
        idempotency_key = self._build_idempotency_key(
            strategy_id, symbol, side, order_timestamp, data
        )
        dedup_key = REDIS_KEY_ORDER_DEDUP.format(idempotency_key=idempotency_key)
        if not await self.redis.set(dedup_key, "1", ex=ORDER_DEDUP_TTL_SECONDS, nx=True):
            log_structured(
                "info",
                "memory_order_duplicate_skipped",
                idempotency_key=idempotency_key,
                symbol=symbol,
                trace_id=trace_id,
            )
            return

        order_id = str(uuid.uuid4())
        vwap_plan: list[float] | None = None
        lock_key = REDIS_KEY_ORDER_LOCK.format(symbol=symbol)
        lock_value = str(uuid.uuid4())

        if not await self.redis.set(lock_key, lock_value, ex=ORDER_LOCK_TTL_SECONDS, nx=True):
            raise RuntimeError(f"Order lock already held for {symbol}")

        try:
            # Snapshot position AFTER acquiring the lock so concurrent orders
            # for the same symbol cannot race on a stale position read.
            prior_position = await self.broker.get_position(symbol)
            if reject_unmatched_sell(side=side, prior_position=prior_position):
                log_structured(
                    "warning",
                    "execution_sell_rejected_no_open_position_memory",
                    symbol=symbol,
                    trace_id=trace_id,
                )
                store = get_runtime_store()
                store.reject_sell_no_position(
                    symbol=symbol,
                    trace_id=trace_id,
                    event_id=order_id,
                    reason="NO_OPEN_POSITION",
                )
                # Store is updated first so the rejection is locally recorded
                # even if the publish below fails.  A transient bus failure does
                # not warrant propagating the exception — the dedup key is already
                # set so any redelivery is a silent no-op.
                try:
                    await self.bus.publish(
                        STREAM_SELL_REJECTED,
                        {
                            FieldName.TYPE: "sell_rejected",
                            FieldName.REJECTION_REASON: "NO_OPEN_POSITION",
                            FieldName.SYMBOL: symbol,
                            FieldName.SIDE: side,
                            FieldName.QTY: qty,
                            FieldName.ORDER_ID: order_id,
                            FieldName.IDEMPOTENCY_KEY: idempotency_key,
                            FieldName.TRACE_ID: trace_id,
                            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                            FieldName.SOURCE: SOURCE_EXECUTION,
                        },
                    )
                except Exception:
                    log_structured(
                        "warning",
                        "sell_rejected_event_publish_failed_memory",
                        symbol=symbol,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        exc_info=True,
                    )
                return

            # Clamp oversell: never sell more than the open position holds.
            if side in (OrderSide.SELL, PositionSide.SHORT):
                prior_qty = float(prior_position.get(FieldName.QTY) or 0)
                if prior_qty > 0 and qty > prior_qty:
                    log_structured(
                        "warning",
                        "execution_sell_qty_clamped_to_available",
                        symbol=symbol,
                        requested_qty=qty,
                        available_qty=prior_qty,
                        trace_id=trace_id,
                    )
                    qty = prior_qty

            # Clamp overbuy: never let a BUY push the resulting long position
            # past the per-symbol exposure cap. The pre-trade size bound for
            # BUYs (mirrors the oversell clamp above) — without it a runaway or
            # hallucinated Kelly SIZE_PCT could open an unbounded position.
            if side in (OrderSide.BUY, PositionSide.LONG):
                max_position = min(settings.MAX_SYMBOL_EXPOSURE, settings.MAX_OPEN_POSITION_QTY)
                capped_qty = clamp_buy_to_position_limit(prior_position, qty, max_position)
                if capped_qty <= 0:
                    log_structured(
                        "warning",
                        "execution_buy_rejected_position_limit",
                        symbol=symbol,
                        requested_qty=qty,
                        max_position_qty=max_position,
                        current_position_qty=signed_position_qty(prior_position),
                        trace_id=trace_id,
                    )
                    return
                if capped_qty < qty:
                    log_structured(
                        "warning",
                        "execution_buy_qty_clamped_to_position_limit",
                        symbol=symbol,
                        requested_qty=qty,
                        clamped_qty=capped_qty,
                        max_position_qty=max_position,
                        trace_id=trace_id,
                    )
                    qty = capped_qty

            # Compute VWAP plan after oversell clamping so the slicing plan
            # reflects the actual executed quantity, not the requested qty.
            vwap_plan = self._build_vwap_plan(qty)
            await self.redis.set(REDIS_KEY_IN_FLIGHT_ORDER, "1", ex=IN_FLIGHT_TTL_SECONDS)
            _bracket_t0 = time.monotonic()
            broker_result = await self.broker.place_order(symbol, side, qty, price)
            self._record_exec_tool(
                TOOL_BRACKET_ORDER,
                latency_ms=(time.monotonic() - _bracket_t0) * 1000,
                success=True,
            )
            fill_price = float(broker_result[FieldName.FILL_PRICE])
            filled_at = datetime.now(timezone.utc)

            realized_pnl = compute_realized_pnl(prior_position, side, qty, fill_price)
            entry_price = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
            is_close = is_round_trip_close(prior_position, side, qty)
            pnl_value = realized_pnl if is_close else None
            pnl_percent = compute_pnl_percent(prior_position, side, qty, entry_price, realized_pnl)

            ctx = FillContext(
                order_id=order_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                fill_price=fill_price,
                entry_price=entry_price,
                signal_confidence=signal_confidence,
                pnl_value=pnl_value,
                pnl_percent=pnl_percent,
                realized_pnl=realized_pnl,
                is_round_trip_close=is_close,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                vwap_plan=vwap_plan,
                filled_at=filled_at,
                model_used=str(data.get(FieldName.MODEL_USED) or ""),
                primary_edge=str(data.get(FieldName.PRIMARY_EDGE) or ""),
                decision_cost_usd=float(data.get(FieldName.DECISION_COST_USD) or 0.0),
            )
            await self._record_fill_to_store(
                ctx, broker_order_id=str(broker_result[FieldName.BROKER_ORDER_ID])
            )
            await publish_fill_events(self.bus, ctx)

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
            # Record realized PnL for cooling-off gate and clear in-flight flag
            if realized_pnl != 0.0:
                try:
                    await self.redis.lpush(REDIS_KEY_RECENT_OUTCOMES, str(realized_pnl))
                    await self.redis.ltrim(
                        REDIS_KEY_RECENT_OUTCOMES, 0, REDIS_RECENT_OUTCOMES_MAXLEN - 1
                    )
                except Exception:
                    pass
            try:
                await self.redis.delete(REDIS_KEY_IN_FLIGHT_ORDER)
            except Exception:
                pass
        finally:
            await self.redis.delete(lock_key)

        if self.agent_state:
            self.agent_state.record_event(_STATE_NAME, task=f"order_filled_memory:{symbol}")

        try:
            await _write_heartbeat(
                self.redis,
                _STATE_NAME,
                f"order_filled_memory:{symbol} side={side} fill_price={fill_price}",
                self._decisions_evaluated,
            )
        except Exception:
            log_structured("warning", "execution_heartbeat_failed_memory", exc_info=True)

    # -------------------------------------------------------------------------
    # Gate helpers — add logging and heartbeats on top of pure utils
    # -------------------------------------------------------------------------

    async def _write_idle_heartbeat(
        self, symbol: str, exec_status: str, trace_id: str = ""
    ) -> None:
        """Write a heartbeat even when no order executes so the dashboard always shows EE status."""
        try:
            await _write_heartbeat(
                self.redis,
                _STATE_NAME,
                f"decision:{symbol} {exec_status}",
                self._decisions_evaluated,
                extra={FieldName.EXEC_STATUS: exec_status, FieldName.LAST_TRACE_ID: trace_id},
            )
        except Exception:
            log_structured("warning", "execution_idle_heartbeat_failed", exc_info=True)

    async def _parse_and_validate(self, data: dict[str, Any]) -> _ParsedDecision | None:
        """Delegate to ``parse_decision_fields``, adding logging and a heartbeat on failure."""
        parsed, error = parse_decision_fields(data)
        if error is not None:
            symbol_hint = str(data.get(FieldName.SYMBOL) or "?")
            log_structured("warning", "order_validation_failed", reason=error, symbol=symbol_hint)
            heartbeat_status = ":".join(error.split(":")[:2])
            await self._write_idle_heartbeat(symbol_hint, heartbeat_status)
            return None
        if await self._is_fallback_blocked(parsed, data):
            return None
        return parsed

    async def _is_fallback_blocked(self, parsed: _ParsedDecision, payload: dict[str, Any]) -> bool:
        side = str(parsed.side or "").lower()
        if side not in {OrderSide.BUY, OrderSide.SELL}:
            return False
        reason = str(payload.get(FieldName.REASON) or "").lower()
        source = str(payload.get(FieldName.SOURCE) or "").lower()
        primary_edge = str(payload.get(FieldName.PRIMARY_EDGE) or "").lower()
        llm_succeeded = payload.get(FieldName.LLM_SUCCEEDED)
        is_fallback = (
            llm_succeeded is False
            or "fallback" in reason
            or source == "fallback"
            or primary_edge.startswith("fallback:")
            or primary_edge == "fallback"
            or bool(payload.get(FieldName.FALLBACK_REASON))
        )
        if not is_fallback:
            return False

        # Paper/simulated mode: no live capital at risk — skip the fallback guard.
        # EXECUTION_DECISION_THRESHOLD_MEMORY (0.30) was lowered so rule-based
        # paper signals can execute; blocking them here defeats that intent.
        # NOTE: do NOT use is_db_available() here — a DB outage during live
        # trading must NOT bypass the guard with real capital at risk.
        if settings.BROKER_MODE.lower() == "paper" or settings.ALPACA_PAPER:
            return False

        trace_id = str(parsed.trace_id or "")
        symbol = str(parsed.symbol or "")
        max_allowed = min(settings.MAX_SYMBOL_EXPOSURE, settings.MAX_OPEN_POSITION_QTY)

        if not settings.ALLOW_FALLBACK_TRADES:
            current_signed_qty = 0.0
            blocked = True
        else:
            if parsed.qty > settings.MAX_FALLBACK_ORDER_QTY:
                current_signed_qty = 0.0
                blocked = True
            else:
                current_position = await self.broker.get_position(symbol)
                current_signed_qty = self._signed_position_qty(current_position)
                signed_after = (
                    current_signed_qty + parsed.qty
                    if side == OrderSide.BUY
                    else current_signed_qty - parsed.qty
                )
                # Position-flip/over-close from one side through flat to the other side
                # — always blocked, even when abs(signed_after) < abs(current).
                if current_signed_qty < 0 < signed_after or current_signed_qty > 0 > signed_after:
                    blocked = True
                # Reduce-only is always allowed once fallback trading is enabled.
                elif abs(signed_after) <= abs(current_signed_qty):
                    blocked = False
                # Enforce capped absolute exposure for position-increasing fallback trades.
                elif abs(signed_after) > max_allowed:
                    blocked = True
                else:
                    blocked = False
        if blocked:
            current_qty_for_log = abs(current_signed_qty)
            if current_signed_qty < 0:
                current_qty_for_log = -current_qty_for_log
            log_structured(
                "warning",
                "fallback_trade_blocked",
                reason="fallback_trade_blocked",
                symbol=symbol,
                action=side,
                qty=parsed.qty,
                current_position_qty=current_qty_for_log,
                max_allowed_qty=max_allowed,
                trace_id=trace_id,
            )
            await self._write_idle_heartbeat(symbol, "blocked:fallback_trade", trace_id)
            return True
        return False

    @staticmethod
    def _signed_position_qty(position: dict[str, Any] | None) -> float:
        return signed_position_qty(position)

    @staticmethod
    def _extract_scores(data: dict[str, Any]) -> tuple[float, float]:
        """Thin alias for ``extract_decision_scores`` kept for call-site symmetry."""
        return extract_decision_scores(data)

    @staticmethod
    def _append_equity_snapshot(store: Any, filled_at: datetime) -> None:
        """Append a PnL snapshot to equity_curve after any in-memory fill recording.

        Called from both _process_in_memory and _handle_db_failure so the
        performance-trends chart stays in sync with orders/positions regardless
        of which code path recorded the fill.
        """
        paired = store.paired_pnl_payload()[FieldName.SUMMARY]
        store.equity_curve.append(
            {
                FieldName.TIMESTAMP: filled_at.isoformat(),
                FieldName.VALUE: paired[FieldName.TOTAL_PNL],
                FieldName.REALIZED_PNL: paired[FieldName.REALIZED_PNL],
                FieldName.UNREALIZED_PNL: paired[FieldName.UNREALIZED_PNL],
                FieldName.TOTAL_PNL: paired[FieldName.TOTAL_PNL],
            }
        )
        if len(store.equity_curve) > 1000:
            store.equity_curve = store.equity_curve[-1000:]

    async def _record_fill_to_store(self, ctx: FillContext, *, broker_order_id: str = "") -> None:
        """Record one in-memory fill: order, trade-feed row, broker-mirrored
        position, and an equity snapshot.

        The single in-memory fill-recording path, shared by ``_process_in_memory``
        and the DB-failure fallback so a fill is recorded identically regardless
        of which path saw it. The position is mirrored from the PaperBroker (the
        single source of truth) — never recomputed locally — so the dashboard
        ledger cannot drift from what the engine actually holds.
        """
        store = get_runtime_store()
        store.add_order(
            {
                FieldName.ORDER_ID: ctx.order_id,
                FieldName.STRATEGY_ID: ctx.strategy_id,
                FieldName.SYMBOL: ctx.symbol,
                FieldName.SIDE: ctx.side,
                FieldName.QTY: ctx.qty,
                FieldName.QUANTITY: ctx.qty,
                FieldName.PRICE: ctx.fill_price,
                FieldName.FILLED_PRICE: ctx.fill_price,
                FieldName.STATUS: OrderStatus.FILLED,
                FieldName.BROKER_ORDER_ID: broker_order_id,
                FieldName.PNL: ctx.pnl_value,
                FieldName.SESSION_ID: ctx.strategy_id,
                FieldName.PNL_PERCENT: ctx.pnl_percent,
                FieldName.FILLED_AT: ctx.filled_at.isoformat(),
                FieldName.TRACE_ID: ctx.trace_id,
            }
        )
        store.upsert_trade_fill(
            {
                FieldName.ID: ctx.trace_id,
                FieldName.SYMBOL: ctx.symbol,
                FieldName.SIDE: ctx.side,
                FieldName.QTY: ctx.qty,
                FieldName.ENTRY_PRICE: ctx.entry_price,
                FieldName.EXIT_PRICE: ctx.fill_price if ctx.is_round_trip_close else None,
                FieldName.PNL: ctx.pnl_value,
                FieldName.PNL_PERCENT: ctx.pnl_percent,
                FieldName.SESSION_ID: ctx.strategy_id,
                FieldName.ORDER_ID: ctx.order_id,
                FieldName.EXECUTION_TRACE_ID: ctx.trace_id,
                FieldName.STATUS: OrderStatus.FILLED,
                FieldName.FILLED_AT: ctx.filled_at.isoformat(),
            }
        )
        # A round-trip close is a completed trade — record it so the dashboard's
        # closed-trades panel reflects real activity in memory mode.
        if ctx.is_round_trip_close:
            store.add_closed_trade(
                {
                    FieldName.SYMBOL: ctx.symbol,
                    FieldName.SIDE: ctx.side,
                    FieldName.QTY: ctx.qty,
                    FieldName.ENTRY_PRICE: ctx.entry_price,
                    FieldName.EXIT_PRICE: ctx.fill_price,
                    FieldName.PNL: ctx.realized_pnl,
                    FieldName.PNL_PERCENT: ctx.pnl_percent,
                    FieldName.FILLED_AT: ctx.filled_at.isoformat(),
                }
            )
        # PaperBroker (Redis) is the position source of truth — mirror its
        # authoritative post-fill state instead of recomputing it locally.
        broker_position = await self.broker.get_position(ctx.symbol)
        store.mirror_broker_position(ctx.symbol, broker_position, strategy_id=ctx.strategy_id)
        self._append_equity_snapshot(store, ctx.filled_at)

    async def _apply_kelly_sizing(
        self, data: dict[str, Any], nominal_qty: float, price: float
    ) -> float:
        """Convert SIZE_PCT (Kelly fraction) to absolute share count.

        ReasoningAgent sets SIZE_PCT to the Kelly fraction of portfolio value.
        The nominal QTY in the decision is a unit-count placeholder; this method
        replaces it with a quantity derived from the Kelly fraction so that
        high- and low-confidence decisions actually trade different sizes.
        """
        size_pct = float(data.get(FieldName.SIZE_PCT) or 0.0)
        if size_pct <= 0 or price <= 0:
            return nominal_qty
        try:
            portfolio_value = await self.broker.get_cash()
            kelly_qty = (size_pct * portfolio_value) / price
            if kelly_qty > 0:
                return kelly_qty
        except Exception:
            log_structured("warning", "kelly_sizing_fallback_to_nominal_qty", exc_info=True)
        return nominal_qty

    @staticmethod
    def _record_exec_tool(name: str, *, latency_ms: float, success: bool) -> None:
        """Best-effort telemetry for an execution-phase tool (risk cage / VWAP /
        bracket). These are deterministic mechanics, not directional-alpha
        sources, so they are graded on latency + reliability — never raise into
        the trading path."""
        try:
            get_tool_registry().record_call(name, latency_ms=latency_ms, success=success)
        except Exception:
            log_structured("warning", "execution_tool_telemetry_failed", tool=name, exc_info=True)

    async def _check_pre_execution_gates(
        self,
        side: str,
        symbol: str,
        signal_confidence: float,
        reasoning_score: float,
        trace_id: str,
        *,
        atr_regime_ratio: float | None = None,
        abs_pct_move: float = 0.0,
    ) -> str | None:
        """The deterministic risk cage: run every pre-execution gate and return a
        gate reason string (block) or None (proceed).

        Thin timing wrapper over :meth:`_evaluate_pre_execution_gates` so the
        risk-cage tool records one telemetry sample per evaluated trade
        regardless of which gate fires — making it live in tool governance."""
        t0 = time.monotonic()
        cage_ok = False
        try:
            result = await self._evaluate_pre_execution_gates(
                side,
                symbol,
                signal_confidence,
                reasoning_score,
                trace_id,
                atr_regime_ratio=atr_regime_ratio,
                abs_pct_move=abs_pct_move,
            )
            cage_ok = True  # the cage evaluated cleanly (a gate verdict is not a failure)
            return result
        finally:
            self._record_exec_tool(
                TOOL_RISK_CAGE, latency_ms=(time.monotonic() - t0) * 1000, success=cage_ok
            )

    async def _evaluate_pre_execution_gates(
        self,
        side: str,
        symbol: str,
        signal_confidence: float,
        reasoning_score: float,
        trace_id: str,
        *,
        atr_regime_ratio: float | None = None,
        abs_pct_move: float = 0.0,
    ) -> str | None:
        """Run all pre-execution gates; return gate reason string or None to proceed."""
        final_score = compute_execution_score(signal_confidence, reasoning_score)
        market_open = self._is_market_open(symbol)
        threshold = (
            EXECUTION_DECISION_THRESHOLD_MEMORY
            if not is_db_available()
            else EXECUTION_DECISION_THRESHOLD
        )
        gate = check_execution_gate(side, symbol, final_score, threshold, market_open)
        if gate is not None:
            if gate.startswith("hold:"):
                log_structured(
                    "info",
                    "execution_skipped_advisory_action",
                    symbol=symbol,
                    action=side,
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(symbol, f"idle:hold action={side}", trace_id)
            elif gate.startswith("gated:score:"):
                log_structured(
                    "info",
                    "execution_gated_score_below_threshold",
                    symbol=symbol,
                    final_score=round(final_score, 4),
                    threshold=threshold,
                    signal_confidence=round(signal_confidence, 4),
                    reasoning_score=round(reasoning_score, 4),
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(
                    symbol,
                    f"gated:score score={final_score:.3f}<{threshold}",
                    trace_id,
                )
            elif gate == "blocked:market_closed":
                log_structured(
                    "info",
                    "execution_blocked_market_closed",
                    symbol=symbol,
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(symbol, "blocked:market_closed", trace_id)
            return gate

        # In-flight gate: block new orders while another order is being processed.
        # Prevents rapid signals from stacking before the fill + PnL are recorded.
        if side not in NO_ORDER_ACTIONS:
            try:
                if await self.redis.get(REDIS_KEY_IN_FLIGHT_ORDER):
                    log_structured(
                        "info",
                        "execution_gated_order_in_flight",
                        symbol=symbol,
                        trace_id=trace_id,
                    )
                    await self._write_idle_heartbeat(symbol, "gated:in_flight", trace_id)
                    return "gated:in_flight"
            except Exception:
                pass  # Redis hiccup — do not block the trade

        # Confidence gate: block trades below SIGNAL_CONFIDENCE_MIN_GATE
        if side not in NO_ORDER_ACTIONS:
            conf_gate = check_confidence_gate(signal_confidence, side, SIGNAL_CONFIDENCE_MIN_GATE)
            if conf_gate is not None:
                log_structured(
                    "info",
                    "execution_gated_low_confidence",
                    symbol=symbol,
                    signal_confidence=round(signal_confidence, 4),
                    threshold=SIGNAL_CONFIDENCE_MIN_GATE,
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(
                    symbol,
                    f"gated:low_confidence sc={signal_confidence:.3f}<{SIGNAL_CONFIDENCE_MIN_GATE}",
                    trace_id,
                )
                return conf_gate

        # Regime filter: block trades in low-volatility/choppy markets
        if atr_regime_ratio is not None and side not in NO_ORDER_ACTIONS:
            if atr_regime_ratio < 1.0:
                regime_gate = f"gated:choppy_regime:{atr_regime_ratio:.3f}"
                log_structured(
                    "info",
                    "execution_gated_choppy_regime",
                    symbol=symbol,
                    atr_regime_ratio=round(atr_regime_ratio, 4),
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(
                    symbol,
                    f"gated:choppy_regime atr_ratio={atr_regime_ratio:.3f}",
                    trace_id,
                )
                return regime_gate

        # Net EV gate: block trades where costs exceed expected return
        if abs_pct_move > 0 and side not in NO_ORDER_ACTIONS:
            ev_gate = check_net_ev_gate(signal_confidence, abs_pct_move, SLIPPAGE_PCT_PER_SIDE)
            if ev_gate is not None:
                log_structured(
                    "info",
                    "execution_gated_negative_net_ev",
                    symbol=symbol,
                    signal_confidence=round(signal_confidence, 4),
                    abs_pct_move=abs_pct_move,
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(symbol, ev_gate, trace_id)
                return ev_gate

        # Cooling-off gate: block trades after a streak of recent losses
        cooling_gate = await self._check_cooling_off_gate(symbol, side, trace_id)
        if cooling_gate is not None:
            return cooling_gate

        return None

    async def _check_cooling_off_gate(self, symbol: str, side: str, trace_id: str) -> str | None:
        """Block execution if recent trade outcomes are dominated by losses."""
        if side in NO_ORDER_ACTIONS:
            return None
        try:
            raw = await self.redis.lrange(REDIS_KEY_RECENT_OUTCOMES, 0, COOLING_OFF_WINDOW - 1)
            # LPUSH makes index 0 the newest; cooling_off_score treats the last
            # element as most recent, so reverse to put oldest first.
            outcomes = [float(v) for v in reversed(raw) if v]
            if is_cooling_off(outcomes, decay=COOLING_OFF_DECAY):
                log_structured(
                    "info",
                    "execution_gated_cooling_off",
                    symbol=symbol,
                    recent_outcomes=outcomes,
                    trace_id=trace_id,
                )
                await self._write_idle_heartbeat(
                    symbol, f"gated:cooling_off recent={outcomes}", trace_id
                )
                return "gated:cooling_off"
        except Exception:
            log_structured("warning", "cooling_off_check_failed", exc_info=True)
        return None

    # -------------------------------------------------------------------------
    # Scheduling / clock helpers
    # -------------------------------------------------------------------------

    def _build_idempotency_key(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        timestamp: datetime,
        signal_data: dict[str, Any] | None = None,
    ) -> str:
        ts_minute = timestamp.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
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
        plan = [slice_qty, slice_qty, round(qty - (slice_qty * 2), 8)]
        # Record the VWAP tool only when a slicing plan is actually produced (a
        # large order); small orders skip VWAP, so they are not a tool call.
        self._record_exec_tool(TOOL_VWAP_EXECUTION, latency_ms=0.0, success=True)
        return plan

    def _parse_timestamp(self, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        # Python 3.10 fromisoformat does not accept the 'Z' suffix; normalise first.
        s = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(s)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _is_market_open(self, symbol: str) -> bool:
        """Return True if trading is currently allowed for this symbol.

        Delegates to the centralized MarketStatusService (holiday- and
        early-close-aware) so every stock subsystem shares one clock. Crypto
        trades 24/7; equities follow the regular NYSE/NASDAQ session. Paper mode
        stays always-open so the simulator is testable outside market hours.
        """
        if settings.BROKER_MODE.lower() == "paper" or settings.ALPACA_PAPER:
            return True
        return get_market_status().is_symbol_open(symbol)

    # -------------------------------------------------------------------------
    # Backward-compat delegates — thin wrappers so existing tests don't break
    # -------------------------------------------------------------------------

    def _compute_final_score(
        self, signal_confidence: float, reasoning_score: float, historical_perf: float = 0.6
    ) -> float:
        return compute_execution_score(signal_confidence, reasoning_score, historical_perf)

    def _compute_realized_pnl(
        self, prior_position: dict, side: str, qty: float, fill_price: float
    ) -> float:
        return compute_realized_pnl(prior_position, side, qty, fill_price)

    def _compute_pnl_percent(
        self,
        prior_position: dict,
        side: str,
        qty: float,
        entry_price: float,
        realized_pnl: float,
    ) -> float:
        return compute_pnl_percent(prior_position, side, qty, entry_price, realized_pnl)

    async def _upsert_position(
        self, session, strategy_id: str, symbol: str, side: str, qty: float, fill_price: float
    ) -> None:
        await upsert_position_db(
            session,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            qty=qty,
            fill_price=fill_price,
        )
