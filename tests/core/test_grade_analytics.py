"""Unit tests for grade self-correction analytics (pure math, no I/O).

Mirrors the style of the scoring helpers: deterministic, fast, CI-enforced
(lives under tests/core). Covers anomaly detection, dimension attribution,
trajectory classification, and the end-to-end diagnostic + actionable gate.
"""

from __future__ import annotations

from api.constants import FieldName
from api.services.agents.grade_analytics import (
    DIRECTION_DROP,
    DIRECTION_NORMAL,
    DIRECTION_SPIKE,
    MIN_BASELINE_SAMPLES,
    TREND_DECAYING,
    TREND_IMPROVING,
    TREND_STABLE,
    attribute_anomaly,
    build_self_correction,
    detect_grade_anomaly,
    grade_trajectory,
    is_actionable,
)

# A tight, stable baseline used by several tests.
STABLE_BASELINE = [0.80, 0.81, 0.79, 0.80, 0.82, 0.80]


def _dim_vector(accuracy=0.8, ic=0.6, cost=0.5, latency=0.8):
    return {
        FieldName.ACCURACY: accuracy,
        FieldName.IC_NORMALIZED: ic,
        FieldName.COST_NORMALIZED: cost,
        FieldName.LATENCY_SCORE: latency,
    }


# ---------------------------------------------------------------------------
# detect_grade_anomaly
# ---------------------------------------------------------------------------


class TestDetectGradeAnomaly:
    def test_negative_drop_is_flagged(self):
        result = detect_grade_anomaly(STABLE_BASELINE, 0.40)
        assert result[FieldName.ANOMALY_DETECTED] is True
        assert result[FieldName.DIRECTION] == DIRECTION_DROP
        assert result[FieldName.Z_SCORE] < 0
        assert result[FieldName.BASELINE_SAMPLES] == len(STABLE_BASELINE)

    def test_positive_spike_is_flagged(self):
        result = detect_grade_anomaly(STABLE_BASELINE, 0.99)
        assert result[FieldName.ANOMALY_DETECTED] is True
        assert result[FieldName.DIRECTION] == DIRECTION_SPIKE
        assert result[FieldName.Z_SCORE] > 0

    def test_value_within_baseline_is_not_an_anomaly(self):
        result = detect_grade_anomaly(STABLE_BASELINE, 0.805)
        assert result[FieldName.ANOMALY_DETECTED] is False
        assert result[FieldName.DIRECTION] == DIRECTION_NORMAL

    def test_insufficient_samples_returns_no_anomaly(self):
        # Fewer than MIN_BASELINE_SAMPLES → cannot judge, never fire.
        short = [0.8] * (MIN_BASELINE_SAMPLES - 1)
        result = detect_grade_anomaly(short, 0.05)
        assert result[FieldName.ANOMALY_DETECTED] is False
        assert result[FieldName.Z_SCORE] == 0.0

    def test_zero_variance_baseline_does_not_divide_by_zero(self):
        # All-identical baseline → std 0; must not raise or false-positive.
        result = detect_grade_anomaly([0.5] * 6, 0.95)
        assert result[FieldName.ANOMALY_DETECTED] is False
        assert result[FieldName.BASELINE_STD] == 0.0

    def test_empty_baseline_is_safe(self):
        result = detect_grade_anomaly([], 0.5)
        assert result[FieldName.ANOMALY_DETECTED] is False
        assert result[FieldName.BASELINE_SAMPLES] == 0

    def test_sigma_threshold_is_respected(self):
        # A large move fires at sigma=2.0; a within-noise value never does.
        assert detect_grade_anomaly(STABLE_BASELINE, 0.10, sigma=2.0)[FieldName.ANOMALY_DETECTED]
        assert not detect_grade_anomaly(STABLE_BASELINE, 0.79, sigma=2.0)[
            FieldName.ANOMALY_DETECTED
        ]
        # A higher sigma is stricter: the same move that fires at 2.0 can pass at 50.0.
        assert not detect_grade_anomaly(STABLE_BASELINE, 0.74, sigma=50.0)[
            FieldName.ANOMALY_DETECTED
        ]


# ---------------------------------------------------------------------------
# attribute_anomaly
# ---------------------------------------------------------------------------


class TestAttributeAnomaly:
    def test_identifies_the_collapsed_dimension(self):
        baseline = [_dim_vector(accuracy=0.8)] * 5
        latest = _dim_vector(accuracy=0.2)  # accuracy collapsed
        attribution = attribute_anomaly(baseline, latest)
        assert attribution[0][FieldName.DIMENSION] == FieldName.ACCURACY
        assert attribution[0][FieldName.DELTA] < 0

    def test_sorted_by_absolute_delta_descending(self):
        baseline = [_dim_vector(accuracy=0.8, ic=0.6, cost=0.5, latency=0.8)] * 5
        latest = _dim_vector(accuracy=0.75, ic=0.10, cost=0.5, latency=0.78)
        attribution = attribute_anomaly(baseline, latest)
        deltas = [abs(entry[FieldName.DELTA]) for entry in attribution]
        assert deltas == sorted(deltas, reverse=True)
        assert attribution[0][FieldName.DIMENSION] == FieldName.IC_NORMALIZED

    def test_empty_baseline_returns_empty(self):
        assert attribute_anomaly([], _dim_vector()) == []

    def test_one_entry_per_present_dimension(self):
        baseline = [_dim_vector()] * 3
        attribution = attribute_anomaly(baseline, _dim_vector())
        dims = {entry[FieldName.DIMENSION] for entry in attribution}
        assert dims == {
            FieldName.ACCURACY,
            FieldName.IC_NORMALIZED,
            FieldName.COST_NORMALIZED,
            FieldName.LATENCY_SCORE,
        }


# ---------------------------------------------------------------------------
# grade_trajectory
# ---------------------------------------------------------------------------


class TestGradeTrajectory:
    def test_decaying_series(self):
        result = grade_trajectory([0.9, 0.8, 0.7, 0.6, 0.5])
        assert result[FieldName.DIRECTION] == TREND_DECAYING
        assert result[FieldName.DECAYING] is True
        assert result[FieldName.SLOPE] < 0

    def test_improving_series(self):
        result = grade_trajectory([0.5, 0.6, 0.7, 0.8, 0.9])
        assert result[FieldName.DIRECTION] == TREND_IMPROVING
        assert result[FieldName.DECAYING] is False
        assert result[FieldName.SLOPE] > 0

    def test_flat_series_is_stable(self):
        result = grade_trajectory([0.7, 0.7, 0.7, 0.7, 0.7])
        assert result[FieldName.DIRECTION] == TREND_STABLE
        assert result[FieldName.DECAYING] is False

    def test_insufficient_samples_is_stable(self):
        result = grade_trajectory([0.9, 0.1])
        assert result[FieldName.DIRECTION] == TREND_STABLE
        assert result[FieldName.SLOPE] == 0.0

    def test_tiny_wobble_below_threshold_is_stable(self):
        # Slope magnitude under the decay/improve thresholds stays stable.
        result = grade_trajectory([0.700, 0.701, 0.699, 0.700, 0.701])
        assert result[FieldName.DIRECTION] == TREND_STABLE


# ---------------------------------------------------------------------------
# build_self_correction + is_actionable
# ---------------------------------------------------------------------------


class TestBuildSelfCorrectionAndActionable:
    def test_full_diagnostic_shape(self):
        baseline_vectors = [_dim_vector()] * len(STABLE_BASELINE)
        diag = build_self_correction(
            STABLE_BASELINE,
            0.40,
            baseline_vectors,
            _dim_vector(accuracy=0.2),
            [*STABLE_BASELINE, 0.40],
        )
        # All documented keys present.
        for key in (
            FieldName.ANOMALY_DETECTED,
            FieldName.Z_SCORE,
            FieldName.DIRECTION,
            FieldName.BASELINE_MEAN,
            FieldName.BASELINE_STD,
            FieldName.BASELINE_SAMPLES,
            FieldName.TRAJECTORY,
            FieldName.ATTRIBUTION,
            FieldName.MESSAGE,
        ):
            assert key in diag
        assert isinstance(diag[FieldName.MESSAGE], str) and diag[FieldName.MESSAGE]
        assert isinstance(diag[FieldName.ATTRIBUTION], list)

    def test_drop_is_actionable(self):
        baseline_vectors = [_dim_vector()] * len(STABLE_BASELINE)
        diag = build_self_correction(
            STABLE_BASELINE,
            0.40,
            baseline_vectors,
            _dim_vector(accuracy=0.2),
            [*STABLE_BASELINE, 0.40],
        )
        assert is_actionable(diag) is True

    def test_decaying_trend_without_anomaly_is_actionable(self):
        # No single-point anomaly, but a clear downward trend → still act.
        scores = [0.90, 0.80, 0.70, 0.60, 0.50]
        baseline_vectors = [_dim_vector()] * len(scores[:-1])
        diag = build_self_correction(
            scores[:-1],
            scores[-1],
            baseline_vectors,
            _dim_vector(),
            scores,
        )
        assert diag[FieldName.TRAJECTORY][FieldName.DECAYING] is True
        assert is_actionable(diag) is True

    def test_healthy_stable_is_not_actionable(self):
        stable = [0.80] * 6
        baseline_vectors = [_dim_vector()] * len(stable)
        diag = build_self_correction(
            stable,
            0.81,
            baseline_vectors,
            _dim_vector(),
            [*stable, 0.81],
        )
        assert is_actionable(diag) is False

    def test_positive_spike_is_not_actionable(self):
        baseline_vectors = [_dim_vector()] * len(STABLE_BASELINE)
        diag = build_self_correction(
            STABLE_BASELINE,
            0.99,
            baseline_vectors,
            _dim_vector(),
            [*STABLE_BASELINE, 0.99],
        )
        assert diag[FieldName.DIRECTION] == DIRECTION_SPIKE
        assert is_actionable(diag) is False
