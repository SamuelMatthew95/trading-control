"""DB write operations for orders, positions, and audit log.

All functions accept an AsyncSession and keyword-only parameters — they do
not create sessions themselves, so the caller controls transaction boundaries.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from api.constants import SOURCE_EXECUTION, FieldName, OrderSide, OrderStatus, PositionSide
from api.schema_version import DB_SCHEMA_VERSION


async def insert_pending_order(
    session,
    *,
    strategy_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    idempotency_key: str,
    status: str,
) -> str:
    """INSERT a pending order row and return its integer id as a string."""
    result = await session.execute(
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
            "status": status,
            "source": SOURCE_EXECUTION,
            "schema_version": DB_SCHEMA_VERSION,
        },
    )
    return str(result.scalar_one())


async def insert_rejected_order_once(
    session,
    *,
    idempotency_key: str,
    strategy_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
) -> tuple[str, bool]:
    """Insert a REJECTED order row keyed by idempotency_key; return (order_id, created).

    ON CONFLICT DO NOTHING ensures concurrent replays cannot double-insert.
    Returns created=False when the row already existed so the caller skips
    re-publishing the sell_rejected event.
    """
    result = await session.execute(
        text(
            "INSERT INTO orders "
            "(strategy_id, symbol, side, qty, quantity, price, status, "
            " idempotency_key, broker_order_id, source, schema_version) "
            "VALUES (:strategy_id, :symbol, :side, :qty, :qty, :price, :status, "
            "        :idempotency_key, NULL, :source, :schema_version) "
            "ON CONFLICT (idempotency_key) DO NOTHING "
            "RETURNING id"
        ),
        {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "idempotency_key": idempotency_key,
            "status": OrderStatus.REJECTED,
            "source": SOURCE_EXECUTION,
            "schema_version": DB_SCHEMA_VERSION,
        },
    )
    row = result.first()
    if row is None:
        existing = await session.execute(
            text("SELECT id FROM orders WHERE idempotency_key = :key"),
            {"key": idempotency_key},
        )
        order_id = str(existing.scalar_one())
        return order_id, False
    return str(row[0]), True


async def update_order_fill(
    session,
    *,
    order_id: str,
    status: str,
    broker_order_id: str,
    fill_price: float,
    qty: float,
    filled_at: Any,
) -> None:
    """UPDATE an order row with fill data once the broker confirms execution."""
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
            "status": status,
            "broker_order_id": broker_order_id,
            "fill_price": fill_price,
            "qty": qty,
            "filled_at": filled_at,
            "order_id": order_id,
        },
    )


async def upsert_position_db(
    session,
    *,
    strategy_id: str,
    symbol: str,
    side: str,
    qty: float,
    fill_price: float,
) -> None:
    """INSERT a new position or UPDATE the existing one with signed-qty math."""
    existing = await session.execute(
        text(
            "SELECT id, side, qty FROM positions "
            "WHERE strategy_id = :strategy_id AND symbol = :symbol"
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
                " unrealised_pnl, unrealized_pnl, strategy_id, "
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
                FieldName.CURRENT_PRICE: fill_price,
                "market_value": market_value,
                "strategy_id": strategy_id,
                "schema_version": DB_SCHEMA_VERSION,
                "source": SOURCE_EXECUTION,
            },
        )
        return

    existing_side = str(row[FieldName.SIDE]).lower()
    existing_qty = float(row[FieldName.QTY])
    existing_signed = (
        existing_qty if existing_side in {PositionSide.LONG, OrderSide.BUY} else (-1 * existing_qty)
    )
    new_qty = existing_signed + signed_qty
    next_side = (
        PositionSide.FLAT
        if abs(new_qty) < 1e-9
        else (PositionSide.LONG if new_qty > 0 else PositionSide.SHORT)
    )
    new_abs_qty = abs(new_qty)
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
            FieldName.CURRENT_PRICE: fill_price,
            "market_value": round(new_abs_qty * fill_price, 8),
            FieldName.POSITION_ID: row[FieldName.ID],
        },
    )


async def insert_audit_log(session, *, event_type: str, payload: dict[str, Any]) -> None:
    """Append one row to the audit_log table."""
    await session.execute(
        text(
            "INSERT INTO audit_log (event_type, payload) "
            "VALUES (:event_type, CAST(:payload AS JSONB))"
        ),
        {"event_type": event_type, "payload": json.dumps(payload, default=str)},
    )
