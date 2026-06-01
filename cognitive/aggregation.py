"""FEATURE AGGREGATION LAYER — the one structure that may enter the decision engine.

Raw agent payloads are normalized into a flat ``{news, tech, macro, risk}`` dict
of floats. ONLY this structure crosses into the deterministic decision engine —
no agent object, no LLM text, no confidence side-channel — which is what keeps
the decision step a pure function of (features, weights).

Normalization choices (documented so they cannot silently drift):
  * ``news`` / ``tech`` are confidence-weighted (signal × the agent's own
    confidence), so a tentative read contributes less than a sure one.
  * ``macro`` passes through (the spec's macro signal carries no confidence).
  * ``risk`` passes through in [0, 1]; it is an annotation for the risk engine
    and is intentionally NOT part of the decision score.
"""

from __future__ import annotations

from typing import Any

from cognitive.agents import clamp, clamp01

# The exact keys the decision engine consumes. Frozen on purpose.
FEATURE_KEYS: tuple[str, ...] = ("news", "tech", "macro", "risk")


def aggregate(
    news: dict[str, Any],
    tech: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
) -> dict[str, float]:
    """Fold the four agent payloads into the normalized feature vector."""
    return {
        "news": round(
            clamp(float(news.get("sentiment", 0.0)) * float(news.get("confidence", 1.0))), 6
        ),
        "tech": round(clamp(float(tech.get("trend", 0.0)) * float(tech.get("confidence", 1.0))), 6),
        "macro": round(clamp(float(macro.get("regime", 0.0))), 6),
        "risk": round(clamp01(float(risk.get("risk_score", 0.0))), 6),
    }
