"""Grade self-correction analytics — anomaly detection + trajectory.

Pure, side-effect-free helpers (mirrors :mod:`api.services.agents.scoring`):
zero I/O, no DB, no Redis, no logging. The :class:`GradeAgent` feeds its
rolling history of composite grade scores in here every cycle; this module
decides whether the latest grade is a statistical anomaly relative to the
recent baseline, attributes the deviation to one of the four scoring
dimensions, and classifies the recent grade *trajectory*
(improving / stable / decaying).

This is the trading-domain analogue of the "systemic weight calibration" and
"predictive decay" ideas: it lets the learning loop react to a *trend* of
degrading grades — and to one-off shocks — **before** the hard D/F retirement
gates in ``GradeAgent._take_grade_action`` ever fire.
"""

from __future__ import annotations

import math
from typing import Any

from api.constants import FieldName

# --- Tunable defaults ------------------------------------------------------
# Owned by this single-purpose module, exactly like the grade thresholds in
# ``scoring.py``. They are not cross-module contracts, so they live here rather
# than in ``api/constants.py``.
DEFAULT_ANOMALY_SIGMA: float = 2.0
"""|z-score| at or above which the latest grade is flagged as an anomaly."""

MIN_BASELINE_SAMPLES: int = 5
"""Minimum prior grades required before an anomaly z-score is meaningful."""

MIN_TRAJECTORY_SAMPLES: int = 4
"""Minimum grades required to fit a trend slope."""

DECAY_SLOPE_THRESHOLD: float = -0.02
"""Per-cycle score slope at or below which the trajectory is decaying."""

IMPROVE_SLOPE_THRESHOLD: float = 0.02
"""Per-cycle score slope at or above which the trajectory is improving."""

# Direction / trend labels (these are dict *values*, never dict keys).
DIRECTION_DROP: str = "negative_drop"
DIRECTION_SPIKE: str = "positive_spike"
DIRECTION_NORMAL: str = "normal"
TREND_IMPROVING: str = "improving"
TREND_STABLE: str = "stable"
TREND_DECAYING: str = "decaying"

# The four scoring dimensions, in the same order GradeAgent weights them.
GRADE_DIMENSIONS: tuple[str, ...] = (
    FieldName.ACCURACY,
    FieldName.IC_NORMALIZED,
    FieldName.COST_NORMALIZED,
    FieldName.LATENCY_SCORE,
)

_EPSILON: float = 1e-9


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sample_std(xs: list[float], mean: float) -> float:
    """Sample standard deviation (n-1 denominator). 0.0 for fewer than 2 points."""
    if len(xs) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(max(variance, 0.0))


def detect_grade_anomaly(
    baseline_scores: list[float],
    latest_score: float,
    *,
    sigma: float = DEFAULT_ANOMALY_SIGMA,
    min_samples: int = MIN_BASELINE_SAMPLES,
) -> dict[str, Any]:
    """Flag the latest grade as an anomaly versus the rolling baseline.

    Always returns the baseline statistics so the caller can surface them even
    when no anomaly fired. With insufficient samples or a zero-variance
    baseline, ``anomaly_detected`` is ``False`` (we never divide by ~0).
    """
    n = len(baseline_scores)
    mean = _mean(baseline_scores)
    std = _sample_std(baseline_scores, mean)

    z = 0.0
    direction = DIRECTION_NORMAL
    detected = False
    if n >= min_samples and std > _EPSILON:
        z = (latest_score - mean) / std
        if z <= -sigma:
            detected, direction = True, DIRECTION_DROP
        elif z >= sigma:
            detected, direction = True, DIRECTION_SPIKE

    return {
        FieldName.ANOMALY_DETECTED: detected,
        FieldName.Z_SCORE: round(z, 4),
        FieldName.DIRECTION: direction,
        FieldName.BASELINE_MEAN: round(mean, 4),
        FieldName.BASELINE_STD: round(std, 4),
        FieldName.BASELINE_SAMPLES: n,
    }


def attribute_anomaly(
    baseline_dimension_vectors: list[dict[str, Any]],
    latest_dimensions: dict[str, Any],
    *,
    dimensions: tuple[str, ...] = GRADE_DIMENSIONS,
) -> list[dict[str, Any]]:
    """Attribute the grade move to its dimensions, most-deviant first.

    Returns one ``{dimension, delta}`` entry per dimension, where
    ``delta = latest - baseline_mean`` for that dimension, sorted by absolute
    delta descending. Empty when there is no baseline to compare against.
    """
    if not baseline_dimension_vectors:
        return []

    deltas: list[dict[str, Any]] = []
    for dim in dimensions:
        base_vals = [
            float(vec.get(dim, 0.0))
            for vec in baseline_dimension_vectors
            if vec.get(dim) is not None
        ]
        if not base_vals:
            continue
        latest_val = float(latest_dimensions.get(dim, 0.0) or 0.0)
        delta = latest_val - _mean(base_vals)
        deltas.append({FieldName.DIMENSION: dim, FieldName.DELTA: round(delta, 4)})

    deltas.sort(key=lambda d: abs(float(d[FieldName.DELTA])), reverse=True)
    return deltas


def grade_trajectory(
    scores: list[float],
    *,
    min_samples: int = MIN_TRAJECTORY_SAMPLES,
    decay_threshold: float = DECAY_SLOPE_THRESHOLD,
    improve_threshold: float = IMPROVE_SLOPE_THRESHOLD,
) -> dict[str, Any]:
    """Least-squares slope of recent scores → improving / stable / decaying."""
    n = len(scores)
    if n < min_samples:
        return {
            FieldName.SLOPE: 0.0,
            FieldName.DIRECTION: TREND_STABLE,
            FieldName.DECAYING: False,
        }

    mean_x = (n - 1) / 2.0
    mean_y = _mean(scores)
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if denom <= _EPSILON:
        slope = 0.0
    else:
        numer = sum((i - mean_x) * (scores[i] - mean_y) for i in range(n))
        slope = numer / denom

    if slope <= decay_threshold:
        direction = TREND_DECAYING
    elif slope >= improve_threshold:
        direction = TREND_IMPROVING
    else:
        direction = TREND_STABLE

    return {
        FieldName.SLOPE: round(slope, 6),
        FieldName.DIRECTION: direction,
        FieldName.DECAYING: direction == TREND_DECAYING,
    }


def build_self_correction(
    baseline_scores: list[float],
    latest_score: float,
    baseline_dimension_vectors: list[dict[str, Any]],
    latest_dimensions: dict[str, Any],
    recent_scores: list[float],
    *,
    sigma: float = DEFAULT_ANOMALY_SIGMA,
) -> dict[str, Any]:
    """Assemble the structured self-correction diagnostic for one grade cycle.

    ``baseline_*`` are the *prior* cycles (excluding the current grade);
    ``recent_scores`` includes the current score so the trend reflects it.
    """
    anomaly = detect_grade_anomaly(baseline_scores, latest_score, sigma=sigma)
    trajectory = grade_trajectory(recent_scores)
    attribution = attribute_anomaly(baseline_dimension_vectors, latest_dimensions)

    top = attribution[0] if attribution else None
    top_txt = (
        f", driver={top[FieldName.DIMENSION]} Δ{float(top[FieldName.DELTA]):+.3f}" if top else ""
    )
    message = (
        f"grade {anomaly[FieldName.DIRECTION]} "
        f"z={float(anomaly[FieldName.Z_SCORE]):+.2f} vs "
        f"μ={float(anomaly[FieldName.BASELINE_MEAN]):.3f}"
        f"±{float(anomaly[FieldName.BASELINE_STD]):.3f} "
        f"(n={anomaly[FieldName.BASELINE_SAMPLES]}); "
        f"trend={trajectory[FieldName.DIRECTION]} "
        f"slope={float(trajectory[FieldName.SLOPE]):+.4f}{top_txt}"
    )

    return {
        FieldName.ANOMALY_DETECTED: anomaly[FieldName.ANOMALY_DETECTED],
        FieldName.Z_SCORE: anomaly[FieldName.Z_SCORE],
        FieldName.DIRECTION: anomaly[FieldName.DIRECTION],
        FieldName.BASELINE_MEAN: anomaly[FieldName.BASELINE_MEAN],
        FieldName.BASELINE_STD: anomaly[FieldName.BASELINE_STD],
        FieldName.BASELINE_SAMPLES: anomaly[FieldName.BASELINE_SAMPLES],
        FieldName.TRAJECTORY: trajectory,
        FieldName.ATTRIBUTION: attribution,
        FieldName.MESSAGE: message,
    }


def is_actionable(self_correction: dict[str, Any]) -> bool:
    """True when the diagnostic warrants a notification (a drop or a decay).

    Positive spikes are intentionally *not* actionable — we surface them in the
    grade payload for the dashboard but do not page on good news.
    """
    if self_correction.get(FieldName.ANOMALY_DETECTED) and (
        self_correction.get(FieldName.DIRECTION) == DIRECTION_DROP
    ):
        return True
    trajectory = self_correction.get(FieldName.TRAJECTORY) or {}
    return bool(trajectory.get(FieldName.DECAYING))
