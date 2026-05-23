"""Pure technical-indicator math. No IO, no logging — fully unit-testable.

Every function returns ``None`` when there is not enough data to compute a
trustworthy value, so callers can mark the indicator missing rather than
fabricate a number.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    """One OHLCV bar."""

    open: float
    high: float
    low: float
    close: float
    volume: float


def ema_last(values: list[float], period: int) -> float | None:
    """Exponential moving average of the most recent ``period`` window.

    Seeded with a simple average of the first ``period`` values, then smoothed.
    """
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def ema_series(values: list[float], period: int) -> list[float] | None:
    """Full EMA series aligned to ``values[period-1:]`` (one value per bar
    from the seed onward). Used to compute MACD."""
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    out = [ema]
    for v in values[period:]:
        ema = v * k + ema * (1.0 - k)
        out.append(ema)
    return out


def rsi_wilder(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI over ``period`` (needs period+1 closes)."""
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float] | None:
    """Return ``(macd_line, signal_line)`` for the most recent bar, or None."""
    if len(closes) < slow + signal:
        return None
    fast_series = ema_series(closes, fast)
    slow_series = ema_series(closes, slow)
    if fast_series is None or slow_series is None:
        return None
    # Align tails: slow series starts later, so trim the fast series to match.
    offset = slow - fast
    fast_aligned = fast_series[offset:]
    macd_line = [f - s for f, s in zip(fast_aligned, slow_series, strict=False)]
    if len(macd_line) < signal:
        return None
    signal_line = ema_last(macd_line, signal)
    if signal_line is None:
        return None
    return macd_line[-1], signal_line


def atr_wilder(candles: list[Candle], period: int = 14) -> float | None:
    """Wilder's Average True Range over ``period`` (needs period+1 candles)."""
    if len(candles) < period + 1:
        return None
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def vwap(candles: list[Candle]) -> float | None:
    """Volume-weighted average price over the supplied candles."""
    if not candles:
        return None
    pv = 0.0
    vol = 0.0
    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        pv += typical * c.volume
        vol += c.volume
    if vol <= 0:
        return None
    return pv / vol


def relative_volume(candles: list[Candle], lookback: int = 20) -> float | None:
    """Latest bar volume divided by the average of the prior ``lookback`` bars."""
    if len(candles) < lookback + 1:
        return None
    prior = candles[-(lookback + 1) : -1]
    avg = sum(c.volume for c in prior) / lookback
    if avg <= 0:
        return None
    return candles[-1].volume / avg


def support_resistance(candles: list[Candle], lookback: int = 20) -> tuple[float, float] | None:
    """Naive support/resistance: min low / max high over the lookback window."""
    if len(candles) < lookback:
        return None
    window = candles[-lookback:]
    support = min(c.low for c in window)
    resistance = max(c.high for c in window)
    return support, resistance
