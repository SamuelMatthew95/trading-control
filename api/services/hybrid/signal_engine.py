"""Deterministic signal engine.

Computes a :class:`SignalSummary` from OHLCV candles using pure indicator math.
Indicators that cannot be computed (insufficient history) are left ``None`` and
recorded in ``missing_indicators``; ``indicators_complete`` is then False and
the downstream candidate gate / risk engine default to HOLD. No LLM, no IO.
"""

from __future__ import annotations

from api.constants import MarketDirection
from api.services.hybrid.indicators import (
    Candle,
    atr_wilder,
    ema_last,
    macd,
    relative_volume,
    rsi_wilder,
    support_resistance,
    vwap,
)
from api.services.hybrid.models import SignalSummary

# Indicators considered critical for a tradable signal. If any is missing the
# summary is marked incomplete and the pipeline holds.
_CRITICAL = ("ema_9", "ema_20", "vwap", "rsi_14", "atr_14")

# How close (as a fraction of price) counts as "near" a level.
_NEAR_LEVEL_PCT = 0.005


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def build_signal_summary(
    symbol: str,
    candles: list[Candle],
    *,
    price_fresh: bool = True,
    min_relative_volume: float = 0.5,
) -> SignalSummary:
    """Compute a deterministic signal summary for ``symbol``."""
    closes = [c.close for c in candles]
    last_price = closes[-1] if closes else None

    ema_9 = ema_last(closes, 9)
    ema_20 = ema_last(closes, 20)
    ema_50 = ema_last(closes, 50)
    vwap_val = vwap(candles) if candles else None
    rsi = rsi_wilder(closes, 14)
    macd_pair = macd(closes)
    atr = atr_wilder(candles, 14)
    rel_vol = relative_volume(candles, 20)
    levels = support_resistance(candles, 20)

    macd_line = macd_pair[0] if macd_pair else None
    macd_sig = macd_pair[1] if macd_pair else None
    atr_pct = (atr / last_price * 100.0) if (atr is not None and last_price) else None

    support = levels[0] if levels else None
    resistance = levels[1] if levels else None

    # Derived booleans
    price_above_vwap = (
        (last_price > vwap_val) if (last_price is not None and vwap_val is not None) else None
    )
    ema_9_above_ema_20 = (ema_9 > ema_20) if (ema_9 is not None and ema_20 is not None) else None
    ema_20_above_ema_50 = (ema_20 > ema_50) if (ema_20 is not None and ema_50 is not None) else None
    macd_bias: MarketDirection | None = None
    if macd_line is not None and macd_sig is not None:
        # Small tolerance so floating-point noise on a near-flat MACD does not
        # flip the bias to bearish when line and signal are effectively equal.
        macd_bias = (
            MarketDirection.BULLISH if macd_line >= macd_sig - 1e-9 else MarketDirection.BEARISH
        )

    dist_vwap = (
        ((last_price - vwap_val) / vwap_val * 100.0)
        if (last_price is not None and vwap_val)
        else None
    )
    dist_support = (
        ((last_price - support) / support * 100.0) if (last_price is not None and support) else None
    )
    dist_resistance = (
        ((resistance - last_price) / resistance * 100.0)
        if (last_price is not None and resistance)
        else None
    )
    near_resistance = dist_resistance is not None and 0 <= dist_resistance <= _NEAR_LEVEL_PCT * 100
    near_support = dist_support is not None and 0 <= dist_support <= _NEAR_LEVEL_PCT * 100

    # Missing-indicator accounting
    values = {
        "ema_9": ema_9,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "vwap": vwap_val,
        "rsi_14": rsi,
        "atr_14": atr,
        "macd": macd_line,
    }
    missing = [name for name in _CRITICAL if values.get(name) is None]
    indicators_complete = not missing

    volume_valid = rel_vol is not None and rel_vol >= min_relative_volume

    # ----- Scores (deterministic, bounded [0, 1]) -----
    trend_score = _trend_score(price_above_vwap, ema_9_above_ema_20, ema_20_above_ema_50)
    momentum_score = _momentum_score(rsi, macd_bias)
    liquidity_score = _clamp((rel_vol or 0.0) / 2.0)
    volatility_risk = _clamp((atr_pct or 0.0) / 3.0)

    direction = _direction(trend_score, momentum_score)
    setup_type = _setup_type(direction, price_above_vwap, ema_9_above_ema_20)
    confidence_seed = _confidence_seed(
        trend_score, momentum_score, liquidity_score, volatility_risk, indicators_complete
    )

    return SignalSummary(
        symbol=symbol,
        setup_type=setup_type,
        raw_direction=direction,
        confidence_seed=round(confidence_seed, 4),
        trend_score=round(trend_score, 4),
        momentum_score=round(momentum_score, 4),
        liquidity_score=round(liquidity_score, 4),
        volatility_risk=round(volatility_risk, 4),
        ema_9=ema_9,
        ema_20=ema_20,
        ema_50=ema_50,
        vwap=vwap_val,
        rsi_14=rsi,
        macd=macd_line,
        macd_signal=macd_sig,
        atr_14=atr,
        atr_pct=atr_pct,
        relative_volume=rel_vol,
        price_above_vwap=price_above_vwap,
        ema_9_above_ema_20=ema_9_above_ema_20,
        ema_20_above_ema_50=ema_20_above_ema_50,
        macd_bias=macd_bias,
        near_resistance=near_resistance,
        near_support=near_support,
        distance_to_vwap_pct=dist_vwap,
        distance_to_support_pct=dist_support,
        distance_to_resistance_pct=dist_resistance,
        support_levels=[support] if support is not None else [],
        resistance_levels=[resistance] if resistance is not None else [],
        indicators_complete=indicators_complete,
        price_fresh=price_fresh,
        volume_valid=volume_valid,
        missing_indicators=missing,
    )


def _trend_score(
    price_above_vwap: bool | None,
    ema_9_above_ema_20: bool | None,
    ema_20_above_ema_50: bool | None,
) -> float:
    flags = [price_above_vwap, ema_9_above_ema_20, ema_20_above_ema_50]
    known = [f for f in flags if f is not None]
    if not known:
        return 0.0
    return sum(1.0 for f in known if f) / len(known)


def _momentum_score(rsi: float | None, macd_bias: MarketDirection | None) -> float:
    score = 0.0
    parts = 0
    if rsi is not None:
        # Reward RSI in the 50-70 momentum band; penalise overbought/oversold.
        if 50 <= rsi <= 70:
            score += 1.0
        elif 40 <= rsi < 50:
            score += 0.5
        else:
            score += 0.2
        parts += 1
    if macd_bias is not None:
        score += 1.0 if macd_bias is MarketDirection.BULLISH else 0.0
        parts += 1
    return score / parts if parts else 0.0


def _direction(trend_score: float, momentum_score: float) -> MarketDirection:
    combined = (trend_score + momentum_score) / 2.0
    if combined >= 0.6:
        return MarketDirection.BULLISH
    if combined <= 0.35:
        return MarketDirection.BEARISH
    return MarketDirection.NEUTRAL


def _setup_type(
    direction: MarketDirection,
    price_above_vwap: bool | None,
    ema_9_above_ema_20: bool | None,
) -> str:
    if direction is MarketDirection.NEUTRAL:
        return "none"
    if price_above_vwap and direction is MarketDirection.BULLISH:
        return "vwap_reclaim"
    if ema_9_above_ema_20 and direction is MarketDirection.BULLISH:
        return "ema_trend"
    if direction is MarketDirection.BEARISH:
        return "trend_breakdown"
    return "momentum"


def _confidence_seed(
    trend_score: float,
    momentum_score: float,
    liquidity_score: float,
    volatility_risk: float,
    indicators_complete: bool,
) -> float:
    if not indicators_complete:
        return 0.0
    raw = 0.4 * trend_score + 0.3 * momentum_score + 0.2 * liquidity_score
    raw -= 0.2 * volatility_risk
    return _clamp(raw)
