"""Pure functions for position state management and PnL calculation.

No async, no logging, no IO — fully testable without mocking.
"""

from __future__ import annotations

from typing import Any

from api.constants import FieldName, OrderSide, PositionSide


def compute_realized_pnl(
    prior_position: dict[str, Any],
    side: str,
    qty: float,
    fill_price: float,
) -> float:
    """Compute realized PnL when closing or partially closing a position.

    Returns 0.0 when the order opens or adds to a position.
    """
    prior_side = str(prior_position.get(FieldName.SIDE) or PositionSide.FLAT).lower()
    prior_entry = float(prior_position.get(FieldName.ENTRY_PRICE) or fill_price)
    prior_qty = float(prior_position.get(FieldName.QTY) or 0)

    if (
        prior_side == PositionSide.LONG
        and side in (OrderSide.SELL, PositionSide.SHORT)
        and prior_qty > 0
    ):
        closed_qty = min(qty, prior_qty)
        return round((fill_price - prior_entry) * closed_qty, 8)

    if (
        prior_side == PositionSide.SHORT
        and side in (OrderSide.BUY, PositionSide.LONG)
        and prior_qty > 0
    ):
        closed_qty = min(qty, prior_qty)
        return round((prior_entry - fill_price) * closed_qty, 8)

    return 0.0


def compute_pnl_percent(
    prior_position: dict[str, Any],
    side: str,
    qty: float,
    entry_price: float,
    realized_pnl: float,
) -> float:
    """Return percentage return on the closed position's cost basis.

    Uses actual closed_qty (not order qty) so oversell scenarios don't
    inflate the denominator and produce an artificially small percentage.
    """
    if entry_price <= 0 or realized_pnl == 0.0:
        return 0.0
    prior_qty = float(prior_position.get(FieldName.QTY) or 0)
    closed_qty = min(qty, prior_qty) if prior_qty > 0 else qty
    cost_basis = entry_price * (closed_qty if closed_qty > 0 else qty)
    return (realized_pnl / cost_basis) * 100 if cost_basis > 0 else 0.0


def is_round_trip_close(prior_position: dict[str, Any], side: str, qty: float) -> bool:
    """Return True if this order closes (or partially closes) an existing position."""
    prior_side = str(prior_position.get(FieldName.SIDE) or PositionSide.FLAT).lower()
    prior_qty = float(prior_position.get(FieldName.QTY) or 0)
    if prior_qty <= 0:
        return False
    if side in (OrderSide.SELL, PositionSide.SHORT) and prior_side == PositionSide.LONG:
        return True
    if side in (OrderSide.BUY, PositionSide.LONG) and prior_side == PositionSide.SHORT:
        return True
    return False


def reject_unmatched_sell(side: str, prior_position: dict[str, Any]) -> bool:
    """Return True if this is a SELL with no open long position to close."""
    if side not in (OrderSide.SELL, PositionSide.SHORT):
        return False
    prior_side = str(prior_position.get(FieldName.SIDE) or PositionSide.FLAT).lower()
    prior_qty = float(prior_position.get(FieldName.QTY) or 0)
    return not (prior_side == PositionSide.LONG and prior_qty > 0)


def apply_signed_delta(
    existing_pos: dict[str, Any],
    side: str,
    qty: float,
    fill_price: float,
    *,
    strategy_id: str,
    symbol: str,
) -> dict[str, Any] | None:
    """Compute next position state after applying a fill.

    Returns the new position dict, or ``None`` if the position is now flat.
    The caller is responsible for writing this to the store or DB.
    """
    signed_qty = qty if side in {OrderSide.BUY, PositionSide.LONG} else (-1 * qty)
    existing_signed = float(existing_pos.get(FieldName.QTY, 0)) * (
        1
        if str(existing_pos.get(FieldName.SIDE, PositionSide.LONG)).lower()
        in {PositionSide.LONG, OrderSide.BUY}
        else -1
    )
    new_signed = existing_signed + signed_qty
    new_abs_qty = abs(new_signed)

    if new_abs_qty < 1e-9:
        return None  # position is now flat

    new_side = PositionSide.LONG if new_signed > 0 else PositionSide.SHORT
    entry_price = float(existing_pos.get(FieldName.ENTRY_PRICE) or fill_price)
    return {
        FieldName.SYMBOL: symbol,
        FieldName.SIDE: new_side,
        FieldName.QTY: new_abs_qty,
        FieldName.QUANTITY: new_abs_qty,
        FieldName.ENTRY_PRICE: entry_price,
        FieldName.AVG_COST: entry_price,
        FieldName.LAST_PRICE: fill_price,
        FieldName.MARKET_VALUE: round(new_abs_qty * fill_price, 8),
        FieldName.UNREALIZED_PNL: 0.0,
        FieldName.STRATEGY_ID: strategy_id,
    }
