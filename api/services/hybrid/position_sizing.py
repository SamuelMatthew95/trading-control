"""Deterministic position sizing.

The model never chooses quantity. Size is derived from account equity, the
risk-per-trade budget, and the stop distance, then capped by buying power,
symbol exposure, the coarse model size hint, and the reasoning multiplier.
If the result rounds to zero, the order is rejected with ``size_zero``.
"""

from __future__ import annotations

import math

from api.constants import BlockReason, PositionSide, SizeHint
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.models import (
    PortfolioState,
    PositionState,
    RiskDecision,
    SizedOrder,
)

_SIZE_HINT_MULTIPLIER = {
    SizeHint.NONE: 0.0,
    SizeHint.SMALL: 0.5,
    SizeHint.NORMAL: 1.0,
    SizeHint.REDUCE_ONLY: 0.5,
}


def _reject(symbol: str, side: str, entry: float, reason: BlockReason) -> SizedOrder:
    return SizedOrder(symbol=symbol, side=side, qty=0.0, entry=entry, reject_reason=reason)


def size_position(
    *,
    risk: RiskDecision,
    portfolio: PortfolioState,
    position: PositionState,
    config: HybridConfig,
    size_hint: SizeHint,
    min_order_qty: float = 0.0,
    max_order_qty: float | None = None,
) -> SizedOrder:
    """Compute the deterministic order quantity for an approved risk decision."""
    side = risk.decision  # "buy" or "sell" (risk engine guarantees not hold here)
    entry = risk.approved_entry or 0.0
    stop = risk.approved_stop_loss
    take = risk.approved_take_profit

    if side not in ("buy", "sell") or entry <= 0:
        return _reject(
            risk.symbol, side if side in ("buy", "sell") else "buy", entry, BlockReason.SIZE_ZERO
        )

    closing = (side == "sell" and position.side is PositionSide.LONG and position.qty > 0) or (
        side == "buy" and position.side is PositionSide.SHORT and position.qty > 0
    )

    if closing:
        qty = position.qty * (risk.size_multiplier if risk.size_multiplier < 1.0 else 1.0)
        qty = _round_qty(qty)
        if qty <= 0:
            return _reject(risk.symbol, side, entry, BlockReason.SIZE_ZERO)
        return SizedOrder(
            symbol=risk.symbol,
            side=side,
            qty=qty,
            entry=entry,
            stop_loss=stop,
            take_profit=take,
            notional=round(qty * entry, 8),
            risk_dollars=0.0,
        )

    # New entry — risk-based sizing requires a usable stop distance.
    if stop is None or stop <= 0:
        return _reject(risk.symbol, side, entry, BlockReason.MISSING_STOP_LOSS)
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return _reject(risk.symbol, side, entry, BlockReason.SIZE_ZERO)

    risk_dollars = portfolio.equity * config.max_risk_per_trade_pct
    qty = risk_dollars / stop_distance

    # Apply coarse model hint and the reasoning multiplier.
    qty *= _SIZE_HINT_MULTIPLIER.get(size_hint, 1.0)
    qty *= max(0.0, risk.size_multiplier)

    # Cap by buying power. Zero buying power means no capital to open → qty 0.
    qty = min(qty, max(0.0, portfolio.buying_power) / entry)

    # Cap by remaining symbol exposure.
    if portfolio.equity > 0:
        cap = config.max_symbol_exposure_pct * portfolio.equity
        existing_notional = position.qty * (position.entry_price or entry)
        remaining = max(0.0, cap - existing_notional)
        qty = min(qty, remaining / entry)

    if max_order_qty is not None:
        qty = min(qty, max_order_qty)

    qty = _round_qty(qty)
    if qty <= 0 or qty <= min_order_qty:
        return _reject(risk.symbol, side, entry, BlockReason.SIZE_ZERO)

    return SizedOrder(
        symbol=risk.symbol,
        side=side,
        qty=qty,
        entry=entry,
        stop_loss=stop,
        take_profit=take,
        notional=round(qty * entry, 8),
        risk_dollars=round(qty * stop_distance, 8),
    )


def _round_qty(qty: float) -> float:
    """Round down to 8 dp (supports fractional crypto) and clamp tiny values."""
    if qty <= 0:
        return 0.0
    return math.floor(qty * 1e8) / 1e8
