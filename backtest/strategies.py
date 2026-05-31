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

from api.services.signal_generator import (
    MOMENTUM_SIGMA,
    SIGMA_FLOOR_PCT,
    STRONG_MOMENTUM_SIGMA,
    classify_signal,
    compute_return_sigma,
)

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
    """The live production signal: the volatility-normalized momentum decision.

    Exactly ``classify_signal`` fed the same rolling-volatility estimate the live
    SignalGenerator computes from its price history — so the harness measures the
    real thing, not a stale fixed-percentage variant.
    """
    return classify_signal(bar.pct, sigma=compute_return_sigma(bar.history))[-1]


def strong_only(bar: Bar) -> str:
    """Trade only STRONG moves (>= STRONG_MOMENTUM_SIGMA of rolling volatility),
    ignoring the noisier MOMENTUM band the baseline also trades.

    On data with no edge, every trade is a guaranteed loss to slippage, so
    trading less *is* the improvement. A strict subset of the baseline's signals
    (the strong tier only); maps to a one-line production change.
    """
    sigma = compute_return_sigma(bar.history)
    if sigma is None or sigma < SIGMA_FLOOR_PCT:
        return HOLD
    if abs(bar.pct) / sigma < STRONG_MOMENTUM_SIGMA:
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
    to measure competing ideas on equal footing, not to bless this one. Uses the
    same volatility-normalized trigger as the baseline so the comparison is fair.
    """
    sigma = compute_return_sigma(bar.history)
    if sigma is None or sigma < SIGMA_FLOOR_PCT:
        return HOLD
    if abs(bar.pct) / sigma < MOMENTUM_SIGMA:
        return HOLD
    return SELL if bar.pct > 0 else BUY


STRATEGIES: dict[str, Strategy] = {
    "baseline_momentum": baseline_momentum,
    "strong_only": strong_only,
    "confirmed_trend": confirmed_trend,
    "mean_reversion": mean_reversion,
}
