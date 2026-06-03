"""Canonical realized-PnL / win-rate math for memory-mode trade lists.

Single source of truth for how realized PnL, winning/losing counts, and win
rate are derived from a list of in-memory order/trade dicts. A trade is
"closed" only when it carries a realized PnL (a round-trip exit). Opening
fills store ``pnl=None`` and zero-PnL scratches are BOTH excluded from the
win-rate denominator, so the one canonical definition is::

    win_rate = winning / (winning + losing)

Before this module, three memory readers divided by ``len(orders)`` (which
includes opens and scratches) while a fourth divided by ``winning + losing``,
so the same data produced different win rates on different endpoints. DB-mode
readers (``MetricsAggregator.get_pnl_metrics`` / ``get_paired_pnl``) compute
over their own SQL sources but apply this same definition.

Pure — no IO, no logging, no app-state reads.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from api.constants import FieldName


class ClosedTradeStats(NamedTuple):
    """Realized-PnL summary over a list of order/trade dicts."""

    realized_pnl: float
    winning: int
    losing: int
    closed: int  # winning + losing — excludes opens (pnl=None) and zero-PnL scratches
    win_rate: float  # ratio in [0.0, 1.0]; 0.0 when there are no closed trades
    best: float  # most positive realized PnL (0.0 when no closed trades)
    worst: float  # most negative realized PnL (0.0 when no closed trades)


def realized_pnl_of(trade: dict[str, Any]) -> float | None:
    """Realized PnL of one trade dict, or ``None`` when it is an opening fill.

    ``None`` and ``""`` (the EventBus serialises ``None`` to ``""``) both mean
    "no realized PnL yet" — an open. Any non-numeric value is treated the same
    way rather than raising, so a malformed row never breaks aggregation.
    """
    raw = trade.get(FieldName.PNL)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def win_rate_from_counts(winning: int, losing: int) -> float:
    """Canonical win rate: ``winning / (winning + losing)``; 0.0 when none closed."""
    closed = winning + losing
    return (winning / closed) if closed else 0.0


def closed_trade_stats(trades: list[dict[str, Any]]) -> ClosedTradeStats:
    """Canonical realized-PnL summary; opens and scratches stay out of the rate."""
    realized = [pnl for trade in trades if (pnl := realized_pnl_of(trade)) is not None]
    winning = sum(1 for pnl in realized if pnl > 0)
    losing = sum(1 for pnl in realized if pnl < 0)
    return ClosedTradeStats(
        realized_pnl=round(sum(realized), 8),
        winning=winning,
        losing=losing,
        closed=winning + losing,
        win_rate=win_rate_from_counts(winning, losing),
        best=round(max(realized, default=0.0), 8),
        worst=round(min(realized, default=0.0), 8),
    )
