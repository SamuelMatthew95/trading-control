"""CHALLENGER — the safety validator. Approves or rejects; modifies nothing.

The backtest is the *judge* of whether a change helps; the challenger is the
*guardrail* that asks whether the backtest result can be trusted and is safe:

  * statistical sanity      — enough learning samples AND enough backtest trades.
  * overfitting detection   — an in-sample improvement must persist out-of-sample.
  * risk impact             — the candidate config is valid and does not materially
                              worsen drawdown out-of-sample.
  * historical consistency  — the proposed direction agrees with the attribution
                              evidence (we don't raise a weight the data says is bad).

It never edits config, weights, or files — it only returns approve/reject plus a
risk score and human-readable reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.backtest_gate import BacktestDelta
from cognitive.events import EventType

MIN_LEARNING_SAMPLES = 30
MIN_TRADES = 30
DRAWDOWN_TOLERANCE_PCT = 1.0  # candidate may add at most this much OOS drawdown


@dataclass(frozen=True)
class ChallengerVerdict:
    """Approve/reject plus why — no system mutation is ever performed here."""

    approved: bool
    risk_score: float  # 0 (safe) .. 1 (very risky)
    reasons: list[str]
    checks: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.CHALLENGER_VERDICT.value,
            "approved": self.approved,
            "risk_score": self.risk_score,
            "reasons": list(self.reasons),
            "checks": dict(self.checks),
        }


def review(
    *,
    in_sample: BacktestDelta,
    out_sample: BacktestDelta,
    learning_samples: int,
    candidate_config_valid: bool,
    attribution_supports: bool,
    min_learning_samples: int = MIN_LEARNING_SAMPLES,
    min_trades: int = MIN_TRADES,
    drawdown_tolerance: float = DRAWDOWN_TOLERANCE_PCT,
) -> ChallengerVerdict:
    """Validate a proposal's backtest evidence and return an approve/reject verdict."""
    reasons: list[str] = []

    statistical_sanity = (
        learning_samples >= min_learning_samples
        and out_sample.candidate.trades >= min_trades
        and out_sample.baseline.trades >= min_trades
    )
    if not statistical_sanity:
        reasons.append(
            f"insufficient sample: learning_samples={learning_samples} "
            f"(need {min_learning_samples}), OOS trades "
            f"baseline={out_sample.baseline.trades}/candidate={out_sample.candidate.trades} "
            f"(need {min_trades} each)"
        )

    overfit = in_sample.pnl_delta > 0 and out_sample.pnl_delta <= 0
    no_overfit = not overfit
    if overfit:
        reasons.append(
            f"overfit: improves in-sample (+{in_sample.pnl_delta}%) but not "
            f"out-of-sample ({out_sample.pnl_delta}%)"
        )

    risk_impact_ok = candidate_config_valid and out_sample.drawdown_delta <= drawdown_tolerance
    if not candidate_config_valid:
        reasons.append("candidate config is out of safe bounds")
    elif out_sample.drawdown_delta > drawdown_tolerance:
        reasons.append(
            f"drawdown worsens by {out_sample.drawdown_delta}% out-of-sample "
            f"(tolerance {drawdown_tolerance}%)"
        )

    if not attribution_supports:
        reasons.append("proposed direction is not supported by PnL attribution")

    improves_oos = out_sample.pnl_delta > 0
    if not improves_oos:
        reasons.append(f"no out-of-sample improvement ({out_sample.pnl_delta}%)")

    checks = {
        "statistical_sanity": statistical_sanity,
        "no_overfit": no_overfit,
        "risk_impact_ok": risk_impact_ok,
        "historically_consistent": attribution_supports,
        "improves_out_of_sample": improves_oos,
    }
    approved = all(checks.values())

    risk_score = 0.0
    if not statistical_sanity:
        risk_score += 0.25
    if overfit:
        risk_score += 0.40
    if not risk_impact_ok:
        risk_score += 0.25
    if not attribution_supports:
        risk_score += 0.10
    risk_score = round(min(1.0, risk_score), 4)

    if approved:
        reasons.append(
            f"approved: +{out_sample.pnl_delta}% PnL and "
            f"{out_sample.sharpe_delta:+} Sharpe out-of-sample, drawdown delta "
            f"{out_sample.drawdown_delta:+}%"
        )

    return ChallengerVerdict(
        approved=approved, risk_score=risk_score, reasons=reasons, checks=checks
    )
