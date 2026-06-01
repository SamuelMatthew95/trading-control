"""DECISION ENGINE — deterministic math only. NO LLM or agent may influence it.

The single rule of the whole system:

    score = news·weights.news + tech·weights.tech + macro·weights.macro
    BUY  if score > buy_threshold
    SELL if score < sell_threshold
    else HOLD

It is a pure function of (normalized features, config weights/thresholds). The
``risk`` feature is deliberately excluded from the score — risk is a separate
hard gate, not a soft vote. The per-signal ``breakdown`` (featureᵢ·weightᵢ) is
returned so the learning layer can attribute PnL back to each agent and the UI
can show exactly why a decision happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.config import WEIGHT_KEYS, CognitiveConfig
from cognitive.events import EventType

BUY = "buy"
SELL = "sell"
HOLD = "hold"


@dataclass(frozen=True)
class Decision:
    """The deterministic verdict plus the score breakdown that produced it."""

    action: str
    score: float
    breakdown: dict[str, float]  # signal -> featureᵢ·weightᵢ contribution
    buy_threshold: float
    sell_threshold: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.DECISION.value,
            "action": self.action,
            "score": self.score,
            "breakdown": dict(self.breakdown),
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
        }


def decide(features: dict[str, float], config: CognitiveConfig) -> Decision:
    """Score the features against the config weights/thresholds — pure math."""
    breakdown = {
        key: round(float(features.get(key, 0.0)) * float(config.weights.get(key, 0.0)), 6)
        for key in WEIGHT_KEYS
    }
    score = round(sum(breakdown.values()), 6)
    if score > config.buy_threshold:
        action = BUY
    elif score < config.sell_threshold:
        action = SELL
    else:
        action = HOLD
    return Decision(
        action=action,
        score=score,
        breakdown=breakdown,
        buy_threshold=config.buy_threshold,
        sell_threshold=config.sell_threshold,
    )
