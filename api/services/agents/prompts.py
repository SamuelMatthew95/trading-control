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

FALLBACK_REFLECTION: dict[str, Any] = {
    "winning_factors": ["composite_score"],
    "losing_factors": [],
    "hypotheses": [],
    "regime_edge": {"current_regime": "unknown", "recommendation": "continue monitoring"},
    "time_of_day_patterns": {"best_hours": [], "worst_hours": []},
    "summary": "Insufficient data for analysis.",
}
