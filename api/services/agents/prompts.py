"""LLM prompt templates and fallback constants used across agents."""

from __future__ import annotations

from typing import Any

REFLECTION_SYSTEM_PROMPT = (
    "You are a trading performance analyst. Analyze the provided trade data and return ONLY "
    "valid JSON with these exact keys: winning_factors (list of strings), losing_factors "
    "(list of strings), hypotheses (list of objects with keys: description, confidence 0-1, "
    "type which must be 'parameter' or 'rule' or 'regime'), regime_edge (object with keys: "
    "current_regime and recommendation), time_of_day_patterns (object with keys: best_hours "
    "as list of ints, worst_hours as list of ints), summary (one-line string). "
    "Return ONLY the JSON object, no markdown fences."
)

# ---------------------------------------------------------------------------
# ReAct self-critique prompt — used by ReasoningAgent after initial decision
# ---------------------------------------------------------------------------

REASONING_CRITIQUE_PROMPT = (
    "You are a conservative trading risk critic. You receive a proposed trading decision "
    "along with current IC weights and market risk state. "
    "Return ONLY valid JSON with exactly these keys: "
    "justified (bool — is the decision well-supported by the evidence), "
    "concerns (list of strings — specific risks or contradictions), "
    "recommended_confidence (float 0.0–1.0 — your suggested confidence level), "
    "recommended_action (string — one of: buy, sell, hold, reject). "
    "Be conservative: if IC weights contradict the signal direction, or if recent "
    "similar trades show losses, downgrade confidence or recommend hold/reject. "
    "Return ONLY the JSON object, no markdown fences."
)

# ---------------------------------------------------------------------------
# Evaluator-Optimizer improve prompt — used by ReflectionAgent when
# the first reflection pass produces too few actionable hypotheses
# ---------------------------------------------------------------------------

REFLECTION_IMPROVE_PROMPT = (
    "The previous reflection generated too few actionable hypotheses. "
    "Using the same trade performance data, generate at least 3 specific, testable hypotheses "
    "about what is driving the observed performance pattern. "
    "Each hypothesis must have confidence >= 0.5 and a concrete, actionable description. "
    "Return ONLY valid JSON with the same structure as before: "
    "winning_factors (list of strings), losing_factors (list of strings), "
    "hypotheses (list of objects with keys: description, confidence, type), "
    "regime_edge (object with current_regime and recommendation), "
    "time_of_day_patterns (object with best_hours and worst_hours lists), "
    "summary (one-line string). "
    "Return ONLY the JSON object, no markdown fences."
)

# ---------------------------------------------------------------------------
# Strategy planning prompt — used by StrategyProposer to rank hypotheses
# by expected impact before converting them to proposals
# ---------------------------------------------------------------------------

STRATEGY_PLANNING_PROMPT = (
    "You are a trading strategy planner. Given a list of improvement hypotheses from a "
    "live trading system, create a prioritized implementation plan. "
    "Rank by: expected_impact (higher is better), implementation_ease (simpler first for same impact), "
    "and risk_level (prefer lower-risk changes). "
    "Return ONLY valid JSON with exactly one key: "
    "ranked_indices (list of integers — 0-based indices into the strong_hypotheses list, "
    "ordered highest priority first). "
    "Return ONLY the JSON object, no markdown fences."
)

FALLBACK_REFLECTION: dict[str, Any] = {
    "winning_factors": ["composite_score"],
    "losing_factors": [],
    "hypotheses": [],
    "regime_edge": {"current_regime": "unknown", "recommendation": "continue monitoring"},
    "time_of_day_patterns": {"best_hours": [], "worst_hours": []},
    "summary": "Insufficient data for analysis.",
}
