"""Historical replay harness (Prompt-OS Layer 4).

Replays a set of historical trade records and computes the metrics the
regression gate compares. Reuses ``compute_learning_metrics`` (the same Sharpe /
drawdown / win-rate math the live learning pipeline uses) and adds the two
gate-specific metrics the directive calls out: false-positive rate and average
slippage. Pure — no I/O, no capital.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from api.constants import FieldName
from api.services.agents.trade_scorer import compute_learning_metrics

# Decisions that take a directional position; a losing one is a "false positive".
_ACTIONABLE_SIDES = {"buy", "sell"}


class ReplayMetrics(BaseModel):
    """Aggregate performance of one replayed trade set."""

    trade_count: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_return: float = 0.0
    sharpe_ratio: float = 0.0
    # Negative percentage points (e.g. -5.2 = 5.2% peak-to-trough drawdown).
    max_drawdown: float = 0.0
    false_positive_rate: float = 0.0
    avg_slippage_bps: float = 0.0


class ReplayHarness:
    """Turns a list of historical trade records into :class:`ReplayMetrics`."""

    def replay(self, trades: list[dict[str, Any]]) -> ReplayMetrics:
        if not trades:
            return ReplayMetrics()

        metrics = compute_learning_metrics(trades)

        pnls = [float(t.get(FieldName.PNL) or 0.0) for t in trades]
        total_pnl = sum(pnls)

        actionable = [
            t
            for t in trades
            if str(t.get(FieldName.SIDE) or t.get(FieldName.ACTION) or "").lower()
            in _ACTIONABLE_SIDES
        ]
        if actionable:
            losers = sum(1 for t in actionable if float(t.get(FieldName.PNL) or 0.0) < 0)
            false_positive_rate = losers / len(actionable)
        else:
            false_positive_rate = 0.0

        slippages = [float(t.get(FieldName.SLIPPAGE_BPS) or 0.0) for t in trades]
        avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0

        return ReplayMetrics(
            trade_count=int(metrics.get(FieldName.TOTAL_TRADES) or len(trades)),
            total_pnl=round(total_pnl, 4),
            win_rate=float(metrics.get(FieldName.WIN_RATE) or 0.0),
            avg_return=float(metrics.get(FieldName.AVG_RETURN) or 0.0),
            sharpe_ratio=float(metrics.get(FieldName.SHARPE_RATIO) or 0.0),
            max_drawdown=float(metrics.get(FieldName.MAX_DRAWDOWN) or 0.0),
            false_positive_rate=round(false_positive_rate, 4),
            avg_slippage_bps=round(avg_slippage, 4),
        )
