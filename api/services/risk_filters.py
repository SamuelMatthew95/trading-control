"""Pure risk-filter and position-sizing functions.

No async, no IO — all functions are fully testable without mocking.
Used by ExecutionEngine and ReasoningAgent to enforce:
  - Minimum signal confidence gate
  - ATR-based market regime filter (low-volatility block)
  - Exponential-decay cooling-off filter (after consecutive losses)
  - Transaction-cost-aware net EV gate
  - Kelly-fraction position sizing
"""

from __future__ import annotations

from collections.abc import Sequence


def compute_rsi(prices: Sequence[float], period: int = 14) -> float | None:
    """Compute RSI from a price series. Returns None if insufficient data."""
    if len(prices) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))

    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period

    if avg_loss == 0.0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 4)


def compute_atr_from_prices(prices: Sequence[float], period: int = 14) -> float | None:
    """Compute approximate ATR from a price series.

    Uses |price_t - price_{t-1}| as a true-range proxy (no OHLCV available).
    Returns None if insufficient data.
    """
    if len(prices) < period + 1:
        return None

    true_ranges = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    recent = true_ranges[-period:]
    return round(sum(recent) / period, 8)


def is_regime_tradeable(atr_history: Sequence[float], avg_period: int = 20) -> bool:
    """Return True if current ATR exceeds its rolling average (trending market).

    Blocks trades when the market is in a low-volatility/choppy regime where
    the cost of spread and slippage exceeds expected signal edge.
    Returns True (allow) when there is insufficient ATR history.
    """
    if len(atr_history) < avg_period:
        return True  # Not enough data — allow by default

    current_atr = atr_history[-1]
    avg_atr = sum(atr_history[-avg_period:]) / avg_period

    return current_atr >= avg_atr


def cooling_off_score(
    recent_outcomes: Sequence[float],
    decay: float = 0.7,
) -> float:
    """Compute exponential-decay-weighted loss fraction from recent trade outcomes.

    Each outcome is a float where negative = loss, positive = win.
    Returns a score in [0, 1] where higher = more recent losses.
    Most recent trade has highest weight.
    """
    if not recent_outcomes:
        return 0.0

    total_weight = 0.0
    loss_weight = 0.0
    weight = 1.0

    for outcome in reversed(recent_outcomes):
        total_weight += weight
        if outcome < 0:
            loss_weight += weight
        weight *= decay

    if total_weight == 0:
        return 0.0

    return round(loss_weight / total_weight, 4)


def is_cooling_off(
    recent_outcomes: Sequence[float],
    decay: float = 0.7,
    threshold: float = 0.6,
) -> bool:
    """Return True if recent losses dominate and trading should pause.

    Uses exponential decay so recent losses matter more than older ones.
    """
    return cooling_off_score(recent_outcomes, decay) >= threshold


def compute_net_ev(
    expected_return_pct: float,
    confidence: float,
    slippage_pct: float = 0.0005,
    commission_per_side: float = 0.0,
) -> float:
    """Compute net expected value after transaction costs.

    Args:
        expected_return_pct: Expected return as fraction (e.g. 0.02 = 2%)
        confidence: Model confidence in [0, 1]
        slippage_pct: Estimated slippage per side
        commission_per_side: Commission per side as fraction of trade value

    Returns:
        Net EV as a fraction — positive means the trade has positive expectancy.
    """
    total_cost = (slippage_pct + commission_per_side) * 2
    raw_ev = expected_return_pct * confidence
    return round(raw_ev - total_cost, 6)


def compute_kelly_size(
    win_prob: float,
    win_fraction: float,
    loss_fraction: float,
    kelly_scale: float = 0.25,
    max_risk_pct: float = 0.015,
) -> float:
    """Compute position size using fractional Kelly criterion.

    Kelly formula: f = (p * b - q) / b  where b = win_fraction/loss_fraction,
    p = win_prob, q = 1 - win_prob.

    Args:
        win_prob: Probability of winning (confidence proxy)
        win_fraction: Expected gain as fraction of position (e.g. 0.02 = 2%)
        loss_fraction: Expected loss as fraction of position (e.g. 0.01 = 1%)
        kelly_scale: Fraction of full Kelly to use (0.25 = quarter Kelly)
        max_risk_pct: Maximum risk as fraction of equity (hard cap)

    Returns:
        Position size as fraction of equity in [0, max_risk_pct].
    """
    if win_fraction <= 0 or loss_fraction <= 0 or win_prob <= 0:
        return 0.0

    b = win_fraction / loss_fraction
    full_kelly = (win_prob * b - (1 - win_prob)) / b

    if full_kelly <= 0:
        return 0.0

    scaled = full_kelly * kelly_scale
    return round(min(scaled, max_risk_pct), 6)


def compute_dynamic_position_size(
    confidence: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    kelly_scale: float = 0.25,
    max_risk_pct: float = 0.015,
) -> float:
    """Compute dynamic position size based on signal confidence and risk parameters.

    Uses fractional Kelly with confidence as the win_probability proxy.
    Enforces minimum 2:1 R/R: if take_profit_pct < 2 * stop_loss_pct,
    the take_profit is scaled up to maintain the ratio.

    Args:
        confidence: Signal confidence in [0, 1]
        stop_loss_pct: Stop loss distance as fraction (e.g. 0.02 = 2%)
        take_profit_pct: Take profit distance as fraction (e.g. 0.04 = 4%)
        kelly_scale: Fraction of full Kelly to use
        max_risk_pct: Hard cap on position size

    Returns:
        Position size as fraction of equity in [0, max_risk_pct].
    """
    if confidence <= 0 or stop_loss_pct <= 0:
        return 0.0

    # Enforce minimum 2:1 R/R
    effective_tp = max(take_profit_pct, stop_loss_pct * 2.0)

    return compute_kelly_size(
        win_prob=confidence,
        win_fraction=effective_tp,
        loss_fraction=stop_loss_pct,
        kelly_scale=kelly_scale,
        max_risk_pct=max_risk_pct,
    )
