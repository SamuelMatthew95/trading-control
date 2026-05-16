"""Stream event publishing for completed order fills.

A single ``publish_fill_events`` call sends the same payload to all four
downstream streams (EXECUTIONS, TRADE_PERFORMANCE, TRADE_COMPLETED,
TRADE_LIFECYCLE) so every downstream agent sees a consistent fill picture.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from api.constants import (
    SOURCE_EXECUTION,
    STREAM_EXECUTIONS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_LIFECYCLE,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    OrderStatus,
)
from api.events.bus import EventBus
from api.schema_version import DB_SCHEMA_VERSION


@dataclass(frozen=True)
class FillContext:
    """Immutable snapshot of a completed fill, used to build all stream events."""

    order_id: str
    strategy_id: str
    symbol: str
    side: str
    qty: float
    price: float  # original decision price
    fill_price: float
    entry_price: float
    signal_confidence: float
    pnl_value: float | None  # None when opening a new position
    pnl_percent: float
    realized_pnl: float
    is_round_trip_close: bool
    idempotency_key: str
    trace_id: str
    vwap_plan: list[float] | None
    filled_at: datetime


async def publish_fill_events(bus: EventBus, ctx: FillContext) -> None:
    """Publish EXECUTIONS, TRADE_PERFORMANCE, TRADE_COMPLETED, TRADE_LIFECYCLE events."""
    filled_at_iso = ctx.filled_at.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    await bus.publish(
        STREAM_EXECUTIONS,
        {
            FieldName.TYPE: "order_filled",
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.ORDER_ID: ctx.order_id,
            FieldName.STRATEGY_ID: ctx.strategy_id,
            FieldName.SYMBOL: ctx.symbol,
            FieldName.SIDE: ctx.side,
            FieldName.QTY: ctx.qty,
            FieldName.PRICE: ctx.price,
            FieldName.FILL_PRICE: ctx.fill_price,
            FieldName.PNL: ctx.pnl_value,
            FieldName.CONFIDENCE: ctx.signal_confidence,
            FieldName.FILLED_AT: filled_at_iso,
            FieldName.EXECUTED_AT: filled_at_iso,
            FieldName.SESSION_ID: ctx.strategy_id,
            FieldName.IDEMPOTENCY_KEY: ctx.idempotency_key,
            FieldName.TRACE_ID: ctx.trace_id,
            FieldName.VWAP_PLAN: ctx.vwap_plan,
            FieldName.SOURCE: SOURCE_EXECUTION,
        },
    )

    await bus.publish(
        STREAM_TRADE_PERFORMANCE,
        {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.TYPE: "trade_performance",
            FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
            FieldName.ORDER_ID: ctx.order_id,
            FieldName.TRADE_ID: ctx.order_id,
            FieldName.STRATEGY_ID: ctx.strategy_id,
            FieldName.SYMBOL: ctx.symbol,
            FieldName.SIDE: ctx.side,
            FieldName.QTY: ctx.qty,
            FieldName.QUANTITY: ctx.qty,
            FieldName.FILL_PRICE: ctx.fill_price,
            FieldName.ENTRY_PRICE: ctx.entry_price,
            FieldName.EXIT_PRICE: ctx.fill_price if ctx.is_round_trip_close else None,
            FieldName.PNL: ctx.pnl_value,
            FieldName.PNL_PERCENT: ctx.pnl_percent,
            FieldName.TRACE_ID: ctx.trace_id,
            FieldName.FILLED_AT: filled_at_iso,
            FieldName.ENTRY_TIME: filled_at_iso,
            FieldName.EXIT_TIME: filled_at_iso if ctx.is_round_trip_close else None,
            FieldName.TIMESTAMP: now_iso,
            FieldName.SOURCE: SOURCE_EXECUTION,
            FieldName.SESSION_ID: ctx.strategy_id,
        },
    )

    if ctx.is_round_trip_close:
        await bus.publish(
            STREAM_TRADE_COMPLETED,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.TYPE: "trade_completed",
                FieldName.SOURCE: SOURCE_EXECUTION,
                FieldName.TRACE_ID: ctx.trace_id,
                FieldName.SESSION_ID: ctx.strategy_id,
                FieldName.ORDER_ID: ctx.order_id,
                FieldName.SYMBOL: ctx.symbol,
                FieldName.SIDE: ctx.side,
                FieldName.QTY: ctx.qty,
                FieldName.ENTRY_PRICE: ctx.entry_price,
                FieldName.EXIT_PRICE: ctx.fill_price,
                FieldName.PNL: ctx.realized_pnl,
                FieldName.PNL_PERCENT: ctx.pnl_percent,
                FieldName.TIMESTAMP: now_iso,
                FieldName.EXECUTED_AT: filled_at_iso,
            },
        )

    await bus.publish(
        STREAM_TRADE_LIFECYCLE,
        {
            FieldName.TYPE: "trade_filled",
            FieldName.SYMBOL: ctx.symbol,
            FieldName.SIDE: ctx.side,
            FieldName.QTY: ctx.qty,
            FieldName.ENTRY_PRICE: ctx.entry_price,
            FieldName.EXIT_PRICE: ctx.fill_price if ctx.is_round_trip_close else None,
            FieldName.PNL: ctx.pnl_value,
            FieldName.PNL_PERCENT: ctx.pnl_percent,
            FieldName.ORDER_ID: ctx.order_id,
            FieldName.EXECUTION_TRACE_ID: ctx.trace_id,
            FieldName.STATUS: OrderStatus.FILLED,
            FieldName.FILLED_AT: filled_at_iso,
            FieldName.TIMESTAMP: filled_at_iso,
            FieldName.SESSION_ID: ctx.strategy_id,
            FieldName.SOURCE: SOURCE_EXECUTION,
        },
    )
