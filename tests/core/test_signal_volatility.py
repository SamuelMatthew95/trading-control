"""Unit coverage for the volatility-normalized signal trigger.

``classify_signal`` grades a move by its z-score (``|pct| / sigma``) when a
trustworthy rolling volatility is supplied, and falls back to the fixed-percent
thresholds during warmup. ``compute_return_sigma`` is the pure volatility
estimator both the live agent and the backtest harness feed it.
"""

from __future__ import annotations

import pytest

from api.constants import MarketDirection, SignalStrength, SignalType
from api.services.signal_generator import (
    MOMENTUM_PCT,
    MOMENTUM_SCORE_FLOOR,
    MOMENTUM_SIGMA,
    SIGMA_MIN_SAMPLES,
    STRONG_MOMENTUM_PCT,
    STRONG_MOMENTUM_SCORE_CEIL,
    STRONG_MOMENTUM_SCORE_FLOOR,
    STRONG_MOMENTUM_SIGMA,
    STRONG_MOMENTUM_SIGMA_CEIL,
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
        # z = 3.0 / 1.0 = 3.0 >= STRONG_MOMENTUM_SIGMA (2.5). Graduated score:
        # 80 + ((3.0-2.5)/(4.0-2.5)) * (95-80) = 80 + (1/3)*15 = 85.0
        sig_type, strength, score, direction, action = classify_signal(3.0, sigma=1.0)
        assert sig_type == SignalType.STRONG_MOMENTUM
        assert strength == SignalStrength.HIGH
        assert score == pytest.approx(85.0)
        assert direction == MarketDirection.BULLISH
        assert action == "buy"

    def test_mid_move_grades_momentum(self):
        # z = 2.0 / 1.0 = 2.0 -> halfway between MOMENTUM_SIGMA (1.5) and STRONG
        # (2.5). Graduated score: 55 + 0.5 * (80-55) = 67.5
        sig_type, strength, score, _direction, action = classify_signal(2.0, sigma=1.0)
        assert sig_type == SignalType.MOMENTUM
        assert strength == SignalStrength.NORMAL
        assert score == pytest.approx(67.5)
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


class TestGraduatedConfidence:
    """Issue #324: score graduates WITHIN a tradeable tier instead of pinning to
    a flat floor, so a deeper move earns more confidence. Tier boundaries stay
    exact, so no buy/sell/hold action changes — only the confidence magnitude.
    """

    def test_momentum_floor_unchanged_at_boundary(self):
        # Exactly at the MOMENTUM threshold the graduated score equals the old
        # flat floor — boundary continuity (no momentum trade newly gated).
        _t, _s, score, _d, _a = classify_signal(MOMENTUM_SIGMA, sigma=1.0)
        assert score == pytest.approx(MOMENTUM_SCORE_FLOOR)

    def test_strong_floor_unchanged_at_boundary(self):
        # Exactly at the STRONG threshold the score equals the STRONG floor,
        # matching the MOMENTUM band's upper end (continuous across the seam).
        _t, _s, score, _d, _a = classify_signal(STRONG_MOMENTUM_SIGMA, sigma=1.0)
        assert score == pytest.approx(STRONG_MOMENTUM_SCORE_FLOOR)

    def test_deeper_momentum_scores_higher_than_borderline(self):
        # A near-STRONG momentum move must earn more confidence than a borderline
        # one — the whole point of graduating the score.
        _t1, _s1, borderline, _d1, _a1 = classify_signal(MOMENTUM_SIGMA + 0.01, sigma=1.0)
        _t2, _s2, near_strong, _d2, _a2 = classify_signal(STRONG_MOMENTUM_SIGMA - 0.01, sigma=1.0)
        assert near_strong > borderline
        assert borderline >= MOMENTUM_SCORE_FLOOR
        assert near_strong < STRONG_MOMENTUM_SCORE_FLOOR

    def test_strong_move_saturates_at_ceiling(self):
        # At/above the saturation point the score clamps to the ceiling and never
        # exceeds it, no matter how extreme the move.
        _t1, _s1, at_ceiling, _d1, _a1 = classify_signal(STRONG_MOMENTUM_SIGMA_CEIL, sigma=1.0)
        _t2, _s2, beyond, _d2, _a2 = classify_signal(STRONG_MOMENTUM_SIGMA_CEIL * 5, sigma=1.0)
        assert at_ceiling == pytest.approx(STRONG_MOMENTUM_SCORE_CEIL)
        assert beyond == pytest.approx(STRONG_MOMENTUM_SCORE_CEIL)

    def test_low_tier_score_unchanged(self):
        # Sub-threshold noise keeps its flat 0.30 floor — graduation only lifts
        # tradeable tiers, never the noise floor (keeps noise below the gate).
        _t, strength, score, _d, action = classify_signal(MOMENTUM_SIGMA - 0.5, sigma=1.0)
        assert strength == SignalStrength.LOW
        assert score == 30.0
        assert action == "hold"

    def test_fixed_path_graduates_too(self):
        # Warmup (no sigma) fixed-percent path graduates identically.
        _t, _s, borderline, _d, _a = classify_signal(MOMENTUM_PCT + 0.01)
        _t2, _s2, near_strong, _d2, _a2 = classify_signal(STRONG_MOMENTUM_PCT - 0.01)
        assert near_strong > borderline
        assert borderline >= MOMENTUM_SCORE_FLOOR
