"""DECISION COUNTERFACTUALS — was the chosen action the best available one?

A good decision can lose and a bad one can win, so outcome alone is a poor
teacher. After a trade closes we replay the *other* actions against the SAME
realized market move and measure regret: how much better the best available
action would have done than the one we took.

Given the realized move ``m`` (the price change over the holding window):
  * BUY  (long)  would have made  +m
  * SELL (short) would have made  -m
  * HOLD         would have made   0

The position's realized PnL already encodes side, so the move is recovered as
``move = pnl`` for a long and ``move = -pnl`` for a short — keeping the chosen
action's counterfactual exactly equal to what actually happened.

Pure and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.events import EventType

BUY = "buy"
SELL = "sell"
HOLD = "hold"


@dataclass(frozen=True)
class CounterfactualResult:
    """What each action would have returned, and the regret of the one taken."""

    chosen_action: str
    chosen_pnl_pct: float
    alternatives: dict[str, float]  # action -> hypothetical pnl %
    best_action: str
    best_pnl_pct: float
    regret_pct: float  # best - chosen, always >= 0
    was_best: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.COUNTERFACTUAL.value,
            "chosen_action": self.chosen_action,
            "chosen_pnl_pct": self.chosen_pnl_pct,
            "alternatives": dict(self.alternatives),
            "best_action": self.best_action,
            "best_pnl_pct": self.best_pnl_pct,
            "regret_pct": self.regret_pct,
            "was_best": self.was_best,
        }


def counterfactual(action: str, realized_pnl_pct: float, side: str) -> CounterfactualResult:
    """Compare the taken action against BUY/SELL/HOLD on the same realized move."""
    move = realized_pnl_pct if side == BUY else -realized_pnl_pct
    alternatives = {BUY: round(move, 6), SELL: round(-move, 6), HOLD: 0.0}
    chosen_pnl = alternatives.get(action, 0.0)
    best_action = max(alternatives, key=lambda key: alternatives[key])
    best_pnl = alternatives[best_action]
    regret = round(best_pnl - chosen_pnl, 6)
    return CounterfactualResult(
        chosen_action=action,
        chosen_pnl_pct=chosen_pnl,
        alternatives=alternatives,
        best_action=best_action,
        best_pnl_pct=best_pnl,
        regret_pct=regret,
        was_best=regret <= 1e-9,
    )
