"""Pluggable signal strategies for the backtest harness.

A :data:`Strategy` maps one bar of market context to an action — ``"buy"``,
``"sell"``, or ``"hold"``. ``baseline_momentum`` is the *live* production signal
(via ``classify_signal``); the others are hypotheses the harness can measure
against it WITHOUT touching any live code. Promoting a winner to production is a
separate, deliberate step.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from api.services.signal_generator import MOMENTUM_PCT, STRONG_MOMENTUM_PCT, classify_signal

__all__ = [
    "STRATEGIES",
    "Bar",
    "Strategy",
    "baseline_momentum",
    "confirmed_trend",
    "mean_reversion",
    "strong_only",
]

HOLD, BUY, SELL = "hold", "buy", "sell"


@dataclass(frozen=True)
class Bar:
    """Market context for a single bar, handed to a Strategy."""

    index: int
    price: float
    prev_price: float
    pct: float  # bar-to-bar percent change (as PricePoller computes it)
    history: Sequence[float]  # recent closes, oldest→newest, including this bar


Strategy = Callable[[Bar], str]


def baseline_momentum(bar: Bar) -> str:
    """The live production signal: chase any single-bar move >= MOMENTUM_PCT.

    This is exactly ``classify_signal`` — the harness measures the real thing.
    """
    return classify_signal(bar.pct)[-1]


def strong_only(bar: Bar) -> str:
    """Trade only STRONG moves (>= STRONG_MOMENTUM_PCT), ignoring the noisy
    1.5% band the baseline over-trades.

    On data with no edge, every trade is a guaranteed loss to slippage, so
    trading less *is* the improvement. Maps directly to a one-line production
    change (drop the MOMENTUM band).
    """
    if abs(bar.pct) < STRONG_MOMENTUM_PCT:
        return HOLD
    return BUY if bar.pct > 0 else SELL


def confirmed_trend(bar: Bar, *, lookback: int = 5) -> str:
    """Require ``lookback`` consecutive same-direction bars before entering, so a
    single noise spike no longer triggers a trade."""
    hist = bar.history
    if len(hist) < lookback + 1:
        return HOLD
    diffs = [hist[i + 1] - hist[i] for i in range(len(hist) - lookback - 1, len(hist) - 1)]
    if all(d > 0 for d in diffs):
        return BUY
    if all(d < 0 for d in diffs):
        return SELL
    return HOLD


def mean_reversion(bar: Bar) -> str:
    """Fade the move instead of chasing it: a big up-move => sell, down => buy.

    The opposite hypothesis to the baseline — included so the harness is shown
    to measure competing ideas on equal footing, not to bless this one.
    """
    if abs(bar.pct) < MOMENTUM_PCT:
        return HOLD
    return SELL if bar.pct > 0 else BUY


STRATEGIES: dict[str, Strategy] = {
    "baseline_momentum": baseline_momentum,
    "strong_only": strong_only,
    "confirmed_trend": confirmed_trend,
    "mean_reversion": mean_reversion,
}
