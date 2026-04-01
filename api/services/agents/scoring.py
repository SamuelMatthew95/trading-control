"""Pure math helpers for agent performance scoring.

All functions are side-effect free and have zero I/O dependencies.
Import these from agent classes instead of duplicating the logic.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Grade thresholds and severity mapping
# ---------------------------------------------------------------------------

GRADE_THRESHOLDS: list[tuple[str, float]] = [
    ("A+", 0.90),
    ("A", 0.80),
    ("B", 0.65),
    ("C", 0.50),
    ("D", 0.35),
    ("F", 0.0),
]

GRADE_SEVERITY: dict[str, str | None] = {
    "A+": None,
    "A": None,
    "B": "INFO",
    "C": "WARNING",
    "D": "URGENT",
    "F": "CRITICAL",
}


def spearman_correlation(xs: list[float], ys: list[float]) -> float:
    """Compute Spearman rank correlation without external dependencies."""
    n = len(xs)
    if n < 3:
        return 0.0

    def _rank(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda kv: kv[1])
        ranks = [0.0] * n
        for rank_pos, (orig_idx, _) in enumerate(indexed):
            ranks[orig_idx] = float(rank_pos + 1)
        return ranks

    rank_x = _rank(xs)
    rank_y = _rank(ys)
    d_sq_sum = sum((rx - ry) ** 2 for rx, ry in zip(rank_x, rank_y, strict=False))
    denom = n * (n**2 - 1)
    return 1.0 - (6.0 * d_sq_sum / denom) if denom else 0.0


def score_to_grade(score: float) -> str:
    """Map a [0, 1] score to a letter grade."""
    for letter, threshold in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


def normalize_ic(raw_ic: float) -> float:
    """Map Spearman correlation [-1, 1] to scoring range [0, 1]."""
    return (raw_ic + 1.0) / 2.0


def normalize_cost_eff(pnl_per_dollar: float) -> float:
    """Map pnl/cost ratio to [0, 1]. Zero cost → 0.5 (neutral), +10 → 1.0, -10 → 0.0."""
    return min(max((pnl_per_dollar + 10.0) / 20.0, 0.0), 1.0)


def compute_weighted_score(
    accuracy: float,
    ic_norm: float,
    cost_norm: float,
    latency: float,
    *,
    w_accuracy: float = 0.35,
    w_ic: float = 0.30,
    w_cost: float = 0.20,
    w_latency: float = 0.15,
) -> float:
    """Combine 4 normalized metrics into a single [0, 1] grade score."""
    raw = accuracy * w_accuracy + ic_norm * w_ic + cost_norm * w_cost + latency * w_latency
    return round(min(max(raw, 0.0), 1.0), 4)
