"""Backtest-gated challenger evaluation — the promote/retire brain.

A "challenger" is a candidate strategy proposed to replace or augment the live
baseline signal. Before anything is promoted, it must clear two gates here,
both measured by the backtest harness on identical price data:

1. **Different** — its decisions actually differ from the baseline. A challenger
   that trades identically is pointless. This is the "active and not just doing
   the same thing as the others" check.
2. **Better** — it beats the baseline's return by a margin.

Only a candidate that is BOTH different AND better is recommended for
promotion; everything else is rejected. The evaluation reuses numbers already
produced by ``compare_*`` — it does not re-run a backtest.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtest.compare import StrategyStats

BASELINE_STRATEGY = "baseline_momentum"
# A candidate must beat the baseline return by at least this many points (on the
# same data) before it is worth promoting over the incumbent.
DEFAULT_PROMOTE_MARGIN_PCT = 1.0

PROMOTE = "promote"
REJECT = "reject"


@dataclass(frozen=True)
class ChallengerVerdict:
    """The promote/reject decision for the best candidate vs the baseline."""

    candidate: str
    baseline: str
    is_different: bool
    beats_baseline: bool
    decision: str  # PROMOTE | REJECT
    reason: str
    candidate_stats: StrategyStats
    baseline_stats: StrategyStats


def evaluate_from_stats(
    stats: list[StrategyStats],
    *,
    baseline: str = BASELINE_STRATEGY,
    margin_pct: float = DEFAULT_PROMOTE_MARGIN_PCT,
) -> ChallengerVerdict | None:
    """Pick the best non-baseline candidate and judge it against the baseline.

    ``stats`` is the output of ``compare_on_prices`` / ``compare_strategies`` —
    this reuses those numbers, so no backtest is re-run. Returns ``None`` when
    the baseline or any candidate is missing.
    """
    by_name = {s.name: s for s in stats}
    base = by_name.get(baseline)
    candidates = [s for s in stats if s.name != baseline]
    if base is None or not candidates:
        return None

    best = max(candidates, key=lambda s: s.mean_return_pct)

    # Different = it does not behave identically to the baseline.
    is_different = best.mean_trades != base.mean_trades or (
        abs(best.mean_return_pct - base.mean_return_pct) > 1e-9
    )
    beats_baseline = best.mean_return_pct > base.mean_return_pct + margin_pct

    if is_different and beats_baseline:
        decision = PROMOTE
        reason = (
            f"{best.name} is different from {baseline} and beats it "
            f"({best.mean_return_pct:+.2f}% vs {base.mean_return_pct:+.2f}%)."
        )
    elif not is_different:
        decision = REJECT
        reason = f"{best.name} behaves identically to {baseline} — nothing real to promote."
    else:
        decision = REJECT
        reason = (
            f"{best.name} differs but does not beat {baseline} by {margin_pct:.1f} pts "
            f"({best.mean_return_pct:+.2f}% vs {base.mean_return_pct:+.2f}%)."
        )

    return ChallengerVerdict(
        candidate=best.name,
        baseline=baseline,
        is_different=is_different,
        beats_baseline=beats_baseline,
        decision=decision,
        reason=reason,
        candidate_stats=best,
        baseline_stats=base,
    )
