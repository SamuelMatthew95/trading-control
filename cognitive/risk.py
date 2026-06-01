"""RISK ENGINE — hard constraints only. The Risk Agent's annotation never reaches here.

This gate is pure math over hard limits from the config:
  * max position size (per trade)
  * max exposure (aggregate)
  * max daily loss (a kill-switch-style block on any new trade)

If a limit is violated the trade is BLOCKED. There is no soft scoring and no
agent influence — the ``risk`` feature produced by the Risk Agent is advisory
context for humans/observability, not an input to this decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.config import CognitiveConfig
from cognitive.decision import BUY, SELL, Decision
from cognitive.events import EventType

BLOCK_POSITION_SIZE = "max_position_size"
BLOCK_EXPOSURE = "max_exposure"
BLOCK_DAILY_LOSS = "max_daily_loss"


@dataclass(frozen=True)
class RiskGate:
    """Outcome of the hard-rule check for one decision."""

    allowed: bool
    blocks: list[str]
    requested_position_pct: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.RISK_GATE.value,
            "allowed": self.allowed,
            "blocks": list(self.blocks),
            "requested_position_pct": self.requested_position_pct,
        }


def evaluate_risk(
    decision: Decision,
    *,
    config: CognitiveConfig,
    requested_position_pct: float,
    current_exposure_pct: float = 0.0,
    day_pnl_pct: float = 0.0,
) -> RiskGate:
    """Block the trade if any hard limit is violated. HOLD is never a trade."""
    blocks: list[str] = []
    is_trade = decision.action in (BUY, SELL)
    if is_trade:
        if requested_position_pct > config.max_position_size_pct:
            blocks.append(BLOCK_POSITION_SIZE)
        if current_exposure_pct + requested_position_pct > config.max_exposure_pct:
            blocks.append(BLOCK_EXPOSURE)
        if day_pnl_pct <= -config.max_daily_loss_pct:
            blocks.append(BLOCK_DAILY_LOSS)
    return RiskGate(
        allowed=is_trade and not blocks,
        blocks=blocks,
        requested_position_pct=requested_position_pct,
    )
