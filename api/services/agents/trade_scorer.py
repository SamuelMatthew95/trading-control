"""Deterministic per-trade scoring engine.

Every completed trade is scored across 5 dimensions. No LLM involved.
All inputs are normalized to [0, 1] before weighting.

Final formula:
  overall_score = 0.30 * normalized_return
                + 0.25 * risk_reward_score
                + 0.20 * entry_quality
                + 0.15 * exit_quality
                + 0.10 * signal_alignment
"""

from __future__ import annotations

import math
from typing import Any

from api.constants import FieldName, Grade


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalize(x: float, min_val: float, max_val: float) -> float:
    if max_val <= min_val:
        return 0.5
    return _clamp((x - min_val) / (max_val - min_val))


# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------


def score_normalized_return(pnl_percent: float | None) -> float:
    """Map pnl_percent ∈ [-10%, +10%] → [0, 1]. Neutral (0%) maps to 0.5."""
    pct = float(pnl_percent or 0.0)
    return normalize(pct, -10.0, 10.0)


def score_risk_reward(pnl: float | None, pnl_percent: float | None) -> float:
    """Proxy R/R from sign and magnitude of PnL.

    Profitable trades score above 0.5; the gain magnitude lifts the score
    further. Losing trades score below 0.5.
    """
    pnl_val = float(pnl or 0.0)
    pct = float(pnl_percent or 0.0)
    if pnl_val > 0:
        # +5% maps to ~0.75, +10% maps to ~1.0
        return _clamp(0.5 + (pct / 20.0))
    if pnl_val < 0:
        # -5% maps to ~0.25, -10% maps to 0.0
        return _clamp(0.5 + (pct / 20.0))
    return 0.5


def score_entry_quality(confidence: float | None) -> float:
    """Use signal confidence as a proxy for entry timing quality.

    High-confidence signals = well-timed entries.
    Normalized from range [0.3, 0.95] → [0, 1].
    """
    conf = float(confidence or 0.5)
    return normalize(conf, 0.3, 0.95)


def score_exit_quality(pnl: float | None, pnl_percent: float | None) -> float:
    """Exit quality: how well the agent captured the available move.

    Profitable trade where pnl_pct >= 5% = good exit (≥ 0.8).
    Break-even ≈ 0.5. Loss = below 0.5.
    """
    pct = float(pnl_percent or 0.0)
    return _clamp(0.5 + (pct / 10.0))


def score_signal_alignment(side: str | None, action: str | None) -> float:
    """1.0 if trade direction matches originating signal, 0.5 otherwise."""
    s = str(side or "").lower().strip()
    a = str(action or "").lower().strip()
    if not s or not a:
        return 1.0  # no conflict signal — assume aligned
    if s == a:
        return 1.0
    # buy/long and sell/short are equivalent pairs
    buy_set = {"buy", "long"}
    sell_set = {"sell", "short"}
    if (s in buy_set and a in buy_set) or (s in sell_set and a in sell_set):
        return 1.0
    return 0.5


# ---------------------------------------------------------------------------
# Composite scorer
# ---------------------------------------------------------------------------


def score_trade(trade_data: dict[str, Any]) -> dict[str, Any]:
    """Compute all dimension scores and return a full evaluation payload.

    Accepts a dict with trade event fields (from stream or DB).
    Returns a dict suitable for persisting to trade_evaluations.
    """
    pnl = trade_data.get(FieldName.PNL)
    pnl_pct = trade_data.get(FieldName.PNL_PERCENT)
    confidence = trade_data.get(FieldName.CONFIDENCE) or trade_data.get(FieldName.SIGNAL_CONFIDENCE)
    side = trade_data.get(FieldName.SIDE)
    action = trade_data.get(FieldName.ACTION)
    symbol = trade_data.get(FieldName.SYMBOL)
    trade_id = (
        trade_data.get(FieldName.TRADE_ID)
        or trade_data.get(FieldName.EXECUTION_TRACE_ID)
        or trade_data.get(FieldName.ORDER_ID)
        or trade_data.get(FieldName.TRACE_ID)
        or ""
    )

    norm_return = score_normalized_return(pnl_pct)
    rr_score = score_risk_reward(pnl, pnl_pct)
    entry_q = score_entry_quality(confidence)
    exit_q = score_exit_quality(pnl, pnl_pct)
    sig_align = score_signal_alignment(side, action)

    overall = (
        0.30 * norm_return + 0.25 * rr_score + 0.20 * entry_q + 0.15 * exit_q + 0.10 * sig_align
    )
    overall = _clamp(overall)

    # Timing score = blend of entry and return quality
    timing = _clamp(0.5 * norm_return + 0.5 * entry_q)

    grade = _score_to_grade(overall)
    confidence_out = _clamp(1.0 - abs(overall - 0.5) * 0.5)

    mistakes = _classify_mistakes(entry_q, exit_q, rr_score, sig_align, pnl)
    strengths = _classify_strengths(entry_q, exit_q, rr_score, sig_align, pnl)

    return {
        FieldName.TRADE_EVAL_ID: str(trade_id),
        FieldName.SYMBOL: symbol,
        FieldName.SIDE: side,
        FieldName.PNL: float(pnl) if pnl is not None else None,
        FieldName.PNL_PERCENT: float(pnl_pct) if pnl_pct is not None else None,
        FieldName.ENTRY_QUALITY: round(entry_q, 4),
        FieldName.EXIT_QUALITY: round(exit_q, 4),
        FieldName.TIMING_SCORE: round(timing, 4),
        FieldName.SIGNAL_ALIGNMENT: round(sig_align, 4),
        FieldName.RISK_REWARD: round(rr_score, 4),
        FieldName.OVERALL_SCORE: round(overall, 4),
        FieldName.GRADE: grade,
        FieldName.CONFIDENCE: round(confidence_out, 4),
        FieldName.MISTAKES: mistakes,
        FieldName.STRENGTHS: strengths,
        "norm_return": round(norm_return, 4),
    }


def _score_to_grade(score: float) -> str:
    if score >= 0.90:
        return Grade.A
    if score >= 0.75:
        return Grade.B
    if score >= 0.60:
        return Grade.C
    if score >= 0.40:
        return Grade.D
    return Grade.F


def _classify_mistakes(
    entry_q: float,
    exit_q: float,
    rr_score: float,
    sig_align: float,
    pnl: Any,
) -> list[str]:
    m: list[str] = []
    if entry_q < 0.4:
        m.append("late_entry")
    if exit_q < 0.4:
        m.append("poor_exit")
    if rr_score < 0.35:
        m.append("bad_risk_reward")
    if sig_align < 0.8:
        m.append("misaligned_signal")
    pnl_val = float(pnl) if pnl is not None else 0.0
    if pnl_val < 0 and entry_q < 0.5:
        m.append("premature_entry")
    return m


def _classify_strengths(
    entry_q: float,
    exit_q: float,
    rr_score: float,
    sig_align: float,
    pnl: Any,
) -> list[str]:
    s: list[str] = []
    if entry_q >= 0.7:
        s.append("good_entry_timing")
    if exit_q >= 0.7:
        s.append("clean_exit")
    if rr_score >= 0.65:
        s.append("good_risk_reward")
    if sig_align >= 0.9:
        s.append("trend_alignment")
    pnl_val = float(pnl) if pnl is not None else 0.0
    if pnl_val > 0:
        s.append("profitable")
    return s


# ---------------------------------------------------------------------------
# Reflection quant helpers — operate on a list of evaluations
# ---------------------------------------------------------------------------


def compute_mistake_clusters(
    evaluations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Count mistake frequency and average PnL impact per mistake type."""
    if not evaluations:
        return []

    mistake_pnl: dict[str, list[float]] = {}
    total = len(evaluations)

    for ev in evaluations:
        pnl_val = float(ev.get(FieldName.PNL) or 0.0)
        for m in ev.get(FieldName.MISTAKES, []):
            mistake_pnl.setdefault(str(m), []).append(pnl_val)

    clusters = []
    for mistake_type, pnls in sorted(mistake_pnl.items()):
        frequency = round(len(pnls) / total, 4)
        avg_impact = round(sum(pnls) / len(pnls), 4) if pnls else 0.0
        clusters.append(
            {
                "type": mistake_type,
                "frequency": frequency,
                "impact": avg_impact,
                "count": len(pnls),
            }
        )
    return sorted(clusters, key=lambda c: abs(c["impact"]), reverse=True)


def compute_patterns(evaluations: list[dict[str, Any]]) -> list[str]:
    """Derive human-readable patterns from trade evaluation statistics."""
    if not evaluations:
        return []

    patterns: list[str] = []
    total = len(evaluations)
    wins = [e for e in evaluations if float(e.get(FieldName.PNL) or 0) > 0]
    losses = [e for e in evaluations if float(e.get(FieldName.PNL) or 0) < 0]
    win_rate = len(wins) / total if total else 0

    if win_rate < 0.4:
        patterns.append(f"low win rate ({win_rate:.0%}) — majority of trades are losing")
    elif win_rate > 0.65:
        patterns.append(f"strong win rate ({win_rate:.0%}) — signal quality is high")

    late_entry_rate = (
        sum(1 for e in evaluations if "late_entry" in e.get(FieldName.MISTAKES, [])) / total
    )
    if late_entry_rate > 0.35:
        patterns.append(
            f"late entries in {late_entry_rate:.0%} of trades — entry timing needs improvement"
        )

    poor_exit_rate = (
        sum(1 for e in evaluations if "poor_exit" in e.get(FieldName.MISTAKES, [])) / total
    )
    if poor_exit_rate > 0.35:
        patterns.append(
            f"poor exits in {poor_exit_rate:.0%} of trades — exits are cutting profits short"
        )

    if losses:
        avg_loss_pct = sum(float(e.get(FieldName.PNL_PERCENT) or 0) for e in losses) / len(losses)
        if avg_loss_pct < -3.0:
            patterns.append(
                f"average loss of {avg_loss_pct:.1f}% — consider tighter stop-loss thresholds"
            )

    avg_score = sum(float(e.get(FieldName.OVERALL_SCORE) or 0) for e in evaluations) / total
    if avg_score < 0.5:
        patterns.append("average trade score below 0.5 — overall decision quality is below par")
    elif avg_score > 0.7:
        patterns.append("average trade score above 0.7 — decision quality is strong")

    return patterns


def compute_recommendations(
    mistake_clusters: list[dict[str, Any]], patterns: list[str]
) -> list[str]:
    """Generate actionable recommendations from mistake clusters."""
    recs: list[str] = []
    seen: set[str] = set()

    mapping = {
        "late_entry": "wait for signal confirmation before entering — reduce entry delay",
        "poor_exit": "use trailing stops or take-profit targets to improve exit quality",
        "bad_risk_reward": "filter out trades with R/R below 1.5:1",
        "misaligned_signal": "reject trades where execution direction contradicts signal direction",
        "premature_entry": "require at least 2 confirming indicators before entry",
    }

    for cluster in mistake_clusters:
        if cluster["frequency"] < 0.15:
            continue
        rec = mapping.get(cluster["type"])
        if rec and rec not in seen:
            recs.append(rec)
            seen.add(rec)

    return recs


def compute_learning_metrics(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate agent performance metrics from trade evaluations."""
    if not evaluations:
        return {
            "total_trades": 0,
            FieldName.WIN_RATE: 0.0,
            FieldName.AVG_RETURN: 0.0,
            FieldName.SHARPE_RATIO: 0.0,
            FieldName.MAX_DRAWDOWN: 0.0,
            "avg_score": 0.0,
            FieldName.SCORE_TREND: "insufficient_data",
            FieldName.CONSISTENCY: 0.0,
        }

    pnl_pcts = [float(e.get(FieldName.PNL_PERCENT) or 0.0) for e in evaluations]
    pnls = [float(e.get(FieldName.PNL) or 0.0) for e in evaluations]
    scores = [float(e.get(FieldName.OVERALL_SCORE) or 0.0) for e in evaluations]

    total = len(evaluations)
    win_rate = sum(1 for p in pnls if p > 0) / total
    avg_return = sum(pnl_pcts) / total

    # Sharpe (annualized, assume 252 trading days, each trade = 1 day)
    if total > 1 and any(p != pnl_pcts[0] for p in pnl_pcts):
        mean_r = avg_return
        variance = sum((r - mean_r) ** 2 for r in pnl_pcts) / (total - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0.001 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown from equity curve
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl_val in pnls:
        cumulative += pnl_val
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    avg_score = sum(scores) / total if scores else 0.0

    # Score trend: slope of scores over time (positive = improving)
    score_trend = "stable"
    if total >= 5:
        n = len(scores)
        x_mean = (n - 1) / 2.0
        numerator = sum((i - x_mean) * (s - avg_score) for i, s in enumerate(scores))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator > 0 else 0.0
        if slope > 0.005:
            score_trend = "improving"
        elif slope < -0.005:
            score_trend = "declining"

    # Consistency: 1 - (std / mean) of scores, clipped to [0, 1]
    consistency = 0.0
    if avg_score > 0.01 and total > 1:
        variance = sum((s - avg_score) ** 2 for s in scores) / (total - 1)
        std_s = math.sqrt(variance) if variance > 0 else 0.0
        consistency = _clamp(1.0 - (std_s / avg_score))

    return {
        "total_trades": total,
        FieldName.WIN_RATE: round(win_rate, 4),
        FieldName.AVG_RETURN: round(avg_return, 4),
        FieldName.SHARPE_RATIO: round(sharpe, 4),
        FieldName.MAX_DRAWDOWN: round(-max_dd, 4),
        "avg_score": round(avg_score, 4),
        FieldName.SCORE_TREND: score_trend,
        FieldName.CONSISTENCY: round(consistency, 4),
    }
