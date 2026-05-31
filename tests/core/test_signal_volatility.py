"""Unit coverage for the volatility-normalized signal trigger.

``classify_signal`` grades a move by its z-score (``|pct| / sigma``) when a
trustworthy rolling volatility is supplied, and falls back to the fixed-percent
thresholds during warmup. ``compute_return_sigma`` is the pure volatility
estimator both the live agent and the backtest harness feed it.
"""

from __future__ import annotations

from api.constants import MarketDirection, SignalStrength, SignalType
from api.services.signal_generator import (
    MOMENTUM_PCT,
    SIGMA_MIN_SAMPLES,
    STRONG_MOMENTUM_PCT,
    classify_signal,
    compute_return_sigma,
)


class TestComputeReturnSigma:
    def test_none_when_too_few_samples(self):
        # Two prices => one return, far below the default min sample count.
        assert compute_return_sigma([100.0, 101.0]) is None

    def test_none_on_empty_or_missing(self):
        assert compute_return_sigma([]) is None
        assert compute_return_sigma(None) is None  # type: ignore[arg-type]

    def test_constant_growth_has_zero_volatility(self):
        # Every step is exactly +1% => identical returns => zero stdev.
        prices = [100.0 * (1.01**i) for i in range(10)]
        sigma = compute_return_sigma(prices, min_samples=3)
        assert sigma is not None
        assert abs(sigma) < 1e-9

    def test_more_volatile_series_has_larger_sigma(self):
        calm = [100.0 + (1 if i % 2 else -1) * 0.1 for i in range(40)]
        wild = [100.0 + (1 if i % 2 else -1) * 5.0 for i in range(40)]
        s_calm = compute_return_sigma(calm)
        s_wild = compute_return_sigma(wild)
        assert s_calm is not None and s_wild is not None
        assert s_wild > s_calm

    def test_returns_value_once_enough_samples(self):
        prices = [100.0 + (i % 3) for i in range(SIGMA_MIN_SAMPLES + 5)]
        assert compute_return_sigma(prices) is not None


class TestClassifySignalVolatilityNormalized:
    def test_strong_move_grades_strong(self):
        # z = 3.0 / 1.0 = 3.0 >= STRONG_MOMENTUM_SIGMA (2.5)
        sig_type, strength, score, direction, action = classify_signal(3.0, sigma=1.0)
        assert sig_type == SignalType.STRONG_MOMENTUM
        assert strength == SignalStrength.HIGH
        assert score == 80.0
        assert direction == MarketDirection.BULLISH
        assert action == "buy"

    def test_mid_move_grades_momentum(self):
        # z = 2.0 / 1.0 = 2.0 -> between MOMENTUM_SIGMA (1.5) and STRONG (2.5)
        sig_type, strength, score, _direction, action = classify_signal(2.0, sigma=1.0)
        assert sig_type == SignalType.MOMENTUM
        assert strength == SignalStrength.NORMAL
        assert score == 55.0
        assert action == "buy"

    def test_small_move_holds(self):
        # z = 1.0 / 1.0 = 1.0 < MOMENTUM_SIGMA -> LOW -> hold
        sig_type, strength, _score, _direction, action = classify_signal(1.0, sigma=1.0)
        assert sig_type == SignalType.PRICE_UPDATE
        assert strength == SignalStrength.LOW
        assert action == "hold"

    def test_negative_strong_move_sells(self):
        _t, _s, _sc, direction, action = classify_signal(-3.0, sigma=1.0)
        assert direction == MarketDirection.BEARISH
        assert action == "sell"

    def test_sigma_below_floor_falls_back_to_fixed_thresholds(self):
        # sigma=0 is below SIGMA_FLOOR_PCT -> fixed-% path: 5.0 >= STRONG_MOMENTUM_PCT
        sig_type, _strength, _score, _direction, action = classify_signal(5.0, sigma=0.0)
        assert sig_type == SignalType.STRONG_MOMENTUM
        assert action == "buy"


class TestClassifySignalLegacyFallback:
    """No sigma supplied => the original fixed-percentage behaviour is preserved
    (keeps existing pipeline tests valid during warmup)."""

    def test_fixed_momentum_band(self):
        sig_type, _s, score, _d, action = classify_signal(MOMENTUM_PCT)
        assert sig_type == SignalType.MOMENTUM
        assert score == 55.0
        assert action == "buy"

    def test_fixed_strong_band(self):
        sig_type, strength, _sc, _d, _a = classify_signal(STRONG_MOMENTUM_PCT + 1.0)
        assert sig_type == SignalType.STRONG_MOMENTUM
        assert strength == SignalStrength.HIGH

    def test_fixed_sub_threshold_holds(self):
        sig_type, _s, _sc, _d, action = classify_signal(0.5)
        assert sig_type == SignalType.PRICE_UPDATE
        assert action == "hold"
