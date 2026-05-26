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
from dataclasses import dataclass
from typing import Any

from api.constants import FieldName, Grade, TradeTag

_EARLY_EXIT_MAX_MINUTES = 2.0
_PATIENCE_MIN_MINUTES = 10.0
_ADVERSE_MOVE_PCT = -0.25
_CAPTURED_MOVE_PCT = 0.4
_EXECUTION_DRAG_PCT = 0.5
_CLEAN_EXECUTION_DRAG_PCT = 0.2
_RECOMMENDATION_MIN_FREQUENCY = 0.15
_HIGH_LATENCY_MS = 1200.0
_HIGH_SLIPPAGE_VARIANCE = 0.005
_HIGH_SPREAD_PCT = 0.25
_MAX_TAGS_PER_BUCKET = 6


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
    entry_price = trade_data.get(FieldName.ENTRY_PRICE)
    exit_price = trade_data.get(FieldName.EXIT_PRICE)
    holding_minutes = trade_data.get(FieldName.HOLDING_PERIOD_MINUTES)
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

    context = _build_trade_context(
        side=side,
        pnl=pnl,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        exit_price=exit_price,
        holding_minutes=holding_minutes,
    )

    mistakes = _classify_mistakes(entry_q, exit_q, rr_score, sig_align, pnl, context=context)
    strengths = _classify_strengths(entry_q, exit_q, rr_score, sig_align, pnl, context=context)
    contextual_tags = _derive_contextual_system_tags(trade_data=trade_data, context=context)
    mistakes = _normalize_tags(
        tags=mistakes + contextual_tags[FieldName.MISTAKES],
        bucket=FieldName.MISTAKES,
    )
    strengths = _normalize_tags(
        tags=strengths + contextual_tags[FieldName.STRENGTHS],
        bucket=FieldName.STRENGTHS,
    )

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
        FieldName.NORM_RETURN: round(norm_return, 4),
        # Decision provenance — which model produced the trade, its thesis, and
        # the LLM cost of the decision (for per-model net ROI).
        FieldName.MODEL_USED: str(trade_data.get(FieldName.MODEL_USED) or ""),
        FieldName.PRIMARY_EDGE: str(trade_data.get(FieldName.PRIMARY_EDGE) or ""),
        FieldName.DECISION_COST_USD: float(trade_data.get(FieldName.DECISION_COST_USD) or 0.0),
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
    *,
    context: TradeContext,
) -> list[str]:
    m: list[str] = []
    if entry_q < 0.4:
        m.append(TradeTag.LATE_ENTRY)
    if exit_q < 0.4:
        m.append(TradeTag.POOR_EXIT)
    if rr_score < 0.35:
        m.append(TradeTag.BAD_RISK_REWARD)
    if sig_align < 0.8:
        m.append(TradeTag.MISALIGNED_SIGNAL)
    pnl_val = float(pnl) if pnl is not None else 0.0
    if pnl_val < 0 and entry_q < 0.5:
        m.append(TradeTag.PREMATURE_ENTRY)

    move_pct = context.move_pct
    hold_mins = context.holding_minutes
    if hold_mins is not None and hold_mins < _EARLY_EXIT_MAX_MINUTES and pnl_val < 0:
        m.append(TradeTag.EARLY_EXIT)
    if move_pct is not None and move_pct < _ADVERSE_MOVE_PCT:
        m.append(TradeTag.ADVERSE_PRICE_MOVE)
    if (
        context.adverse_excursion_pct is not None
        and context.adverse_excursion_pct > _EXECUTION_DRAG_PCT
        and pnl_val < 0
    ):
        m.append(TradeTag.EXECUTION_DRAG)
    return sorted({str(tag) for tag in m})


def _classify_strengths(
    entry_q: float,
    exit_q: float,
    rr_score: float,
    sig_align: float,
    pnl: Any,
    *,
    context: TradeContext,
) -> list[str]:
    s: list[str] = []
    if entry_q >= 0.7:
        s.append(TradeTag.GOOD_ENTRY_TIMING)
    if exit_q >= 0.7:
        s.append(TradeTag.CLEAN_EXIT)
    if rr_score >= 0.65:
        s.append(TradeTag.GOOD_RISK_REWARD)
    if sig_align >= 0.9:
        s.append(TradeTag.TREND_ALIGNMENT)
    pnl_val = float(pnl) if pnl is not None else 0.0
    if pnl_val > 0:
        s.append(TradeTag.PROFITABLE)

    move_pct = context.move_pct
    hold_mins = context.holding_minutes
    if hold_mins is not None and hold_mins >= _PATIENCE_MIN_MINUTES and pnl_val > 0:
        s.append(TradeTag.PATIENCE_PAID)
    if move_pct is not None and move_pct > _CAPTURED_MOVE_PCT:
        s.append(TradeTag.CAPTURED_DIRECTIONAL_MOVE)
    if (
        context.adverse_excursion_pct is not None
        and context.adverse_excursion_pct < _CLEAN_EXECUTION_DRAG_PCT
        and pnl_val > 0
    ):
        s.append(TradeTag.CLEAN_EXECUTION)
    return sorted({str(tag) for tag in s})


@dataclass(frozen=True)
class TradeContext:
    side: str
    pnl: float
    pnl_pct: float
    holding_minutes: float | None
    move_pct: float | None
    adverse_excursion_pct: float | None


def _build_trade_context(
    *,
    side: str | None,
    pnl: Any,
    pnl_pct: Any,
    entry_price: Any,
    exit_price: Any,
    holding_minutes: Any,
) -> TradeContext:
    side_norm = str(side or "").strip().lower()
    move_pct = _price_move_percent(side=side_norm, entry_price=entry_price, exit_price=exit_price)
    return TradeContext(
        side=side_norm,
        pnl=float(pnl or 0.0),
        pnl_pct=float(pnl_pct or 0.0),
        holding_minutes=_safe_float(holding_minutes),
        move_pct=move_pct,
        adverse_excursion_pct=(
            _safe_float(abs(float(pnl_pct or 0.0) - move_pct)) if move_pct is not None else None
        ),
    )


def _derive_contextual_system_tags(
    *, trade_data: dict[str, Any], context: TradeContext
) -> dict[str, list[str]]:
    mistakes: list[str] = []
    strengths: list[str] = []
    latency_ms = _safe_float(trade_data.get(FieldName.LATENCY_MS))
    slip_var = _safe_float(trade_data.get(FieldName.SLIPPAGE_VARIANCE))
    spread_pct = _safe_float(trade_data.get(FieldName.SPREAD_PCT))
    current_regime = str(trade_data.get(FieldName.CURRENT_REGIME) or "").strip().lower()
    signal_regime = str(trade_data.get(FieldName.REGIME) or "").strip().lower()
    if latency_ms is not None and latency_ms >= _HIGH_LATENCY_MS:
        mistakes.append(str(TradeTag.SIGNAL_LATENCY))
    if slip_var is not None and slip_var >= _HIGH_SLIPPAGE_VARIANCE:
        mistakes.append(str(TradeTag.FILL_QUALITY_POOR))
    if spread_pct is not None and spread_pct >= _HIGH_SPREAD_PCT:
        mistakes.append(str(TradeTag.LOW_LIQUIDITY_SKEW))
    if current_regime and signal_regime and current_regime != signal_regime:
        mistakes.append(str(TradeTag.REGIME_SHIFT))
    if bool(trade_data.get(FieldName.RATE_LIMIT)):
        mistakes.append(str(TradeTag.API_THROTTLE_PENALTY))
    if bool(trade_data.get(FieldName.DATA_INTEGRITY_ISSUE)):
        mistakes.append(str(TradeTag.DATA_INTEGRITY_ISSUE))
    if (
        context.pnl > 0
        and context.adverse_excursion_pct is not None
        and context.adverse_excursion_pct > 1.0
    ):
        strengths.append(str(TradeTag.REVERSION_LUCK))
    return {FieldName.MISTAKES: sorted(set(mistakes)), FieldName.STRENGTHS: sorted(set(strengths))}


def _normalize_tags(*, tags: list[str], bucket: str) -> list[str]:
    """Return deterministic, non-contradictory, bounded tag lists."""
    unique = {str(t) for t in tags if t}
    if bucket == FieldName.MISTAKES:
        # If both latency + API throttle exist, keep both (root cause + symptom),
        # but remove directional conflict with favorable-move strength tags handled
        # in the strengths bucket.
        ordered = [
            str(TradeTag.DATA_INTEGRITY_ISSUE),
            str(TradeTag.API_THROTTLE_PENALTY),
            str(TradeTag.SIGNAL_LATENCY),
            str(TradeTag.FILL_QUALITY_POOR),
            str(TradeTag.LOW_LIQUIDITY_SKEW),
            str(TradeTag.REGIME_SHIFT),
            str(TradeTag.EXECUTION_DRAG),
            str(TradeTag.ADVERSE_PRICE_MOVE),
            str(TradeTag.EARLY_EXIT),
            str(TradeTag.PREMATURE_ENTRY),
            str(TradeTag.MISALIGNED_SIGNAL),
            str(TradeTag.BAD_RISK_REWARD),
            str(TradeTag.POOR_EXIT),
            str(TradeTag.LATE_ENTRY),
        ]
    else:
        # Avoid showing both "clean_execution" and "reversion_luck" together.
        if str(TradeTag.REVERSION_LUCK) in unique:
            unique.discard(str(TradeTag.CLEAN_EXECUTION))
        ordered = [
            str(TradeTag.TREND_ALIGNMENT),
            str(TradeTag.CLEAN_EXECUTION),
            str(TradeTag.CAPTURED_DIRECTIONAL_MOVE),
            str(TradeTag.PATIENCE_PAID),
            str(TradeTag.GOOD_RISK_REWARD),
            str(TradeTag.CLEAN_EXIT),
            str(TradeTag.GOOD_ENTRY_TIMING),
            str(TradeTag.PROFITABLE),
            str(TradeTag.REVERSION_LUCK),
        ]

    out = [t for t in ordered if t in unique]
    remainder = sorted(unique.difference(out))
    out.extend(remainder)
    return out[:_MAX_TAGS_PER_BUCKET]


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
                FieldName.TYPE: mistake_type,
                FieldName.FREQUENCY: frequency,
                FieldName.IMPACT: avg_impact,
                FieldName.COUNT: len(pnls),
            }
        )
    return sorted(clusters, key=lambda c: abs(c[FieldName.IMPACT]), reverse=True)


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
        sum(1 for e in evaluations if FieldName.LATE_ENTRY in e.get(FieldName.MISTAKES, [])) / total
    )
    if late_entry_rate > 0.35:
        patterns.append(
            f"late entries in {late_entry_rate:.0%} of trades — entry timing needs improvement"
        )

    poor_exit_rate = (
        sum(1 for e in evaluations if FieldName.POOR_EXIT in e.get(FieldName.MISTAKES, [])) / total
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
        str(
            TradeTag.LATE_ENTRY
        ): "wait for signal confirmation before entering — reduce entry delay",
        str(
            TradeTag.POOR_EXIT
        ): "use trailing stops or take-profit targets to improve exit quality",
        str(TradeTag.BAD_RISK_REWARD): "filter out trades with R/R below 1.5:1",
        str(
            TradeTag.MISALIGNED_SIGNAL
        ): "reject trades where execution direction contradicts signal direction",
        str(TradeTag.PREMATURE_ENTRY): "require at least 2 confirming indicators before entry",
        str(
            TradeTag.EARLY_EXIT
        ): "enforce minimum hold time unless stop-loss is hit to avoid noise exits",
        str(
            TradeTag.ADVERSE_PRICE_MOVE
        ): "tighten regime filter when directional move turns against position quickly",
        str(
            TradeTag.EXECUTION_DRAG
        ): "audit slippage/fees and route sizing to reduce execution drag",
        str(
            TradeTag.SIGNAL_LATENCY
        ): "reduce decision-to-execution latency; enforce max stale-signal window",
        str(
            TradeTag.FILL_QUALITY_POOR
        ): "route to higher-liquidity venues or use adaptive limit offsets",
        str(TradeTag.LOW_LIQUIDITY_SKEW): "avoid thin-liquidity windows and widen spread guards",
        str(
            TradeTag.REGIME_SHIFT
        ): "gate entries on regime confirmation to avoid stale strategy assumptions",
        str(
            TradeTag.API_THROTTLE_PENALTY
        ): "add pre-emptive request budgeting and throttle-aware exit logic",
        str(
            TradeTag.DATA_INTEGRITY_ISSUE
        ): "quarantine delayed/corrupt market data before signal generation",
    }

    for cluster in mistake_clusters:
        if cluster[FieldName.FREQUENCY] < _RECOMMENDATION_MIN_FREQUENCY:
            continue
        rec = mapping.get(cluster[FieldName.TYPE])
        if rec and rec not in seen:
            recs.append(rec)
            seen.add(rec)

    return recs


# Minimum number of trades needed for metrics to be considered reliable.
_MIN_RELIABLE_TRADES = 10
_MIN_STABLE_TRADES = 30


def compute_learning_metrics(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate agent performance metrics from trade evaluations."""
    if not evaluations:
        return {
            FieldName.TOTAL_TRADES: 0,
            FieldName.WIN_RATE: 0.0,
            FieldName.AVG_RETURN: 0.0,
            FieldName.SHARPE_RATIO: 0.0,
            FieldName.MAX_DRAWDOWN: 0.0,
            FieldName.AVG_SCORE: 0.0,
            FieldName.SCORE_TREND: "insufficient_data",
            FieldName.CONSISTENCY: 0.0,
            "sample_size": 0,
            "metric_status": "insufficient_data",
            "min_required_sample_size": _MIN_RELIABLE_TRADES,
        }

    pnl_pcts = [float(e.get(FieldName.PNL_PERCENT) or 0.0) for e in evaluations]
    pnls = [float(e.get(FieldName.PNL) or 0.0) for e in evaluations]
    scores = [float(e.get(FieldName.OVERALL_SCORE) or 0.0) for e in evaluations]

    total = len(evaluations)
    # Win rate uses dollar PnL sign to determine wins (positive dollar return = win)
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

    # Max drawdown from equity curve — computed from pnl_percent returns so the
    # result is in the same percentage-point units as avg_return.
    # Using raw dollar pnl values here would produce a dollar-denominated drawdown
    # that the frontend would misinterpret as a fractional return.
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pct in pnl_pcts:
        cumulative += pct
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

    # Classify reliability so callers can qualify displayed metrics.
    if total < _MIN_RELIABLE_TRADES:
        metric_status = "insufficient_data"
    elif total < _MIN_STABLE_TRADES:
        metric_status = "unstable"
    else:
        metric_status = "reliable"

    return {
        FieldName.TOTAL_TRADES: total,
        FieldName.WIN_RATE: round(win_rate, 4),
        FieldName.AVG_RETURN: round(avg_return, 4),
        FieldName.SHARPE_RATIO: round(sharpe, 4),
        # Negative percentage-point drawdown (e.g., -5.2 = 5.2% peak-to-trough drawdown).
        # Units match avg_return so the frontend can display both without scaling.
        FieldName.MAX_DRAWDOWN: round(-max_dd, 4),
        FieldName.AVG_SCORE: round(avg_score, 4),
        FieldName.SCORE_TREND: score_trend,
        FieldName.CONSISTENCY: round(consistency, 4),
        "sample_size": total,
        "metric_status": metric_status,
        "min_required_sample_size": _MIN_RELIABLE_TRADES,
    }


@dataclass
class _ModelAcc:
    """Mutable per-model accumulator. A dataclass (not a dict) so its attribute
    names never collide with the FieldName guardrail's key checks."""

    trades: int = 0
    wins: int = 0
    score_sum: float = 0.0
    pnl_sum: float = 0.0
    cost_sum: float = 0.0


def aggregate_model_performance(evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group scored trades by the LLM that produced them.

    Returns one row per ``model_used`` (skipping blank/unknown) with trade count,
    win rate, average score, and PnL totals — sorted by trade count descending.
    Pure: same aggregation is reused by the DB and in-memory route paths so the
    two modes can never diverge. No LLM, no IO.
    """
    buckets: dict[str, _ModelAcc] = {}
    for ev in evaluations:
        model = str(ev.get(FieldName.MODEL_USED) or "").strip()
        if not model:
            continue
        acc = buckets.setdefault(model, _ModelAcc())
        acc.trades += 1
        pnl = ev.get(FieldName.PNL)
        if pnl is not None:
            pnl_f = float(pnl)
            acc.pnl_sum += pnl_f
            if pnl_f > 0:
                acc.wins += 1
        score = ev.get(FieldName.OVERALL_SCORE)
        if score is not None:
            acc.score_sum += float(score)
        cost = ev.get(FieldName.DECISION_COST_USD)
        if cost is not None:
            acc.cost_sum += float(cost)

    rows = [
        {
            FieldName.MODEL_USED: model,
            FieldName.TRADE_COUNT: acc.trades,
            FieldName.WIN_RATE: round(acc.wins / acc.trades, 4) if acc.trades else 0.0,
            FieldName.AVG_SCORE: round(acc.score_sum / acc.trades, 4) if acc.trades else 0.0,
            FieldName.TOTAL_PNL: round(acc.pnl_sum, 4),
            FieldName.AVG_PNL: round(acc.pnl_sum / acc.trades, 4) if acc.trades else 0.0,
            # LLM cost of the decisions behind these trades, and P&L net of it.
            FieldName.TOTAL_COST: round(acc.cost_sum, 6),
            FieldName.NET_ROI: round(acc.pnl_sum - acc.cost_sum, 4),
        }
        for model, acc in buckets.items()
    ]
    rows.sort(key=lambda r: r[FieldName.TRADE_COUNT], reverse=True)
    return rows


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_move_percent(*, side: str | None, entry_price: Any, exit_price: Any) -> float | None:
    entry = _safe_float(entry_price)
    exit_ = _safe_float(exit_price)
    if entry is None or exit_ is None or entry <= 0:
        return None
    raw = ((exit_ - entry) / entry) * 100.0
    side_norm = str(side or "").strip().lower()
    if side_norm in {"sell", "short"}:
        return -raw
    return raw
