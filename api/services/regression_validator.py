"""Regression validator (Prompt-OS Layer 4) — deterministic promotion gates.

Compares a candidate's replay metrics against the champion's and rejects the
candidate if it is worse on ANY hard gate beyond the configured tolerance.
These checks are deterministic and non-negotiable — the directive's "NO
EXCEPTIONS" rule. The LLM cannot influence this verdict.
"""

from __future__ import annotations

from pydantic import BaseModel

from api.constants import (
    REGRESSION_MAX_DRAWDOWN_DELTA_PCT,
    REGRESSION_MAX_FALSE_POSITIVE_DELTA,
    REGRESSION_MAX_SLIPPAGE_DELTA_BPS,
    REGRESSION_MIN_REPLAY_TRADES,
    REGRESSION_MIN_SHARPE_DELTA,
)
from api.services.replay_harness import ReplayMetrics


class RegressionVerdict(BaseModel):
    approved: bool
    reasons: list[str]
    sharpe_delta: float
    drawdown_delta: float
    false_positive_delta: float
    slippage_delta: float


class RegressionValidator:
    """Applies the hard regression gates to a champion/candidate metric pair."""

    def validate(self, champion: ReplayMetrics, candidate: ReplayMetrics) -> RegressionVerdict:
        sharpe_delta = round(candidate.sharpe_ratio - champion.sharpe_ratio, 4)
        # drawdown is negative; a more-negative candidate delta means worse.
        drawdown_delta = round(candidate.max_drawdown - champion.max_drawdown, 4)
        false_positive_delta = round(
            candidate.false_positive_rate - champion.false_positive_rate, 4
        )
        slippage_delta = round(candidate.avg_slippage_bps - champion.avg_slippage_bps, 4)

        reasons: list[str] = []
        if candidate.trade_count < REGRESSION_MIN_REPLAY_TRADES:
            reasons.append(
                f"insufficient sample: {candidate.trade_count} < "
                f"{REGRESSION_MIN_REPLAY_TRADES} trades"
            )
        if sharpe_delta < REGRESSION_MIN_SHARPE_DELTA:
            reasons.append(
                f"sharpe regressed {sharpe_delta:+.3f} (limit {REGRESSION_MIN_SHARPE_DELTA:+.3f})"
            )
        if drawdown_delta < -REGRESSION_MAX_DRAWDOWN_DELTA_PCT:
            reasons.append(
                f"drawdown worsened {drawdown_delta:+.2f}pp "
                f"(limit -{REGRESSION_MAX_DRAWDOWN_DELTA_PCT:.2f}pp)"
            )
        if false_positive_delta > REGRESSION_MAX_FALSE_POSITIVE_DELTA:
            reasons.append(
                f"false-positive rate up {false_positive_delta:+.3f} "
                f"(limit +{REGRESSION_MAX_FALSE_POSITIVE_DELTA:.3f})"
            )
        if slippage_delta > REGRESSION_MAX_SLIPPAGE_DELTA_BPS:
            reasons.append(
                f"slippage up {slippage_delta:+.2f}bps "
                f"(limit +{REGRESSION_MAX_SLIPPAGE_DELTA_BPS:.2f}bps)"
            )

        return RegressionVerdict(
            approved=not reasons,
            reasons=reasons,
            sharpe_delta=sharpe_delta,
            drawdown_delta=drawdown_delta,
            false_positive_delta=false_positive_delta,
            slippage_delta=slippage_delta,
        )
