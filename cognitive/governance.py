"""PROPOSAL GOVERNANCE — keep the evolution engine from fooling itself with noise.

Without a governor the ProposalAgent can churn out endless near-duplicate tweaks
and re-propose ideas the backtest just rejected. This adds three deterministic
brakes, all enforced BEFORE a proposal is backtested or queued:

  * quota    — at most ``quota`` proposals admitted per ``window`` evolution cycles.
  * dedup    — no exact repeat of a (target, rounded value) still inside the window.
  * cooldown — a target whose proposal was rejected is benched for ``cooldown``
               cycles (novelty / retirement: stop hammering an idea the data rejected).

Pure, deterministic state machine — fully testable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from cognitive.proposal import Proposal

ADMITTED = "admitted"
BLOCKED_QUOTA = "quota_exceeded"
BLOCKED_DUPLICATE = "duplicate"
BLOCKED_COOLDOWN = "cooldown"


@dataclass
class _Admit:
    cycle: int
    key: str


class ProposalGovernor:
    """Deterministic admission control for generated proposals."""

    def __init__(self, *, quota: int = 3, window: int = 10, cooldown: int = 5) -> None:
        self.quota = quota
        self.window = window
        self.cooldown = cooldown
        self._cycle = 0
        self._admitted: deque[_Admit] = deque()
        self._cooldowns: dict[str, int] = {}  # target -> cycle the bench ends
        self._blocked: dict[str, int] = {}

    @staticmethod
    def _key(proposal: Proposal) -> str:
        value = proposal.new_value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = round(float(value), 4)
        return f"{proposal.target}={value}"

    def admit(self, proposal: Proposal) -> tuple[bool, str]:
        """Admit or block a proposal. Returns (admitted, reason)."""
        self._cycle += 1
        while self._admitted and self._admitted[0].cycle <= self._cycle - self.window:
            self._admitted.popleft()

        ends = self._cooldowns.get(proposal.target)
        if ends is not None and self._cycle < ends:
            return self._block(BLOCKED_COOLDOWN)
        key = self._key(proposal)
        if any(entry.key == key for entry in self._admitted):
            return self._block(BLOCKED_DUPLICATE)
        if len(self._admitted) >= self.quota:
            return self._block(BLOCKED_QUOTA)

        self._admitted.append(_Admit(self._cycle, key))
        return True, ADMITTED

    def _block(self, reason: str) -> tuple[bool, str]:
        self._blocked[reason] = self._blocked.get(reason, 0) + 1
        return False, reason

    def record_outcome(self, proposal: Proposal, *, approved: bool) -> None:
        """Bench a rejected proposal's target so it isn't re-proposed immediately."""
        if not approved:
            self._cooldowns[proposal.target] = self._cycle + self.cooldown

    def snapshot(self) -> dict[str, Any]:
        return {
            "cycle": self._cycle,
            "admitted_in_window": len(self._admitted),
            "quota": self.quota,
            "window": self.window,
            "cooldown": self.cooldown,
            "active_cooldowns": {
                target: ends for target, ends in self._cooldowns.items() if ends > self._cycle
            },
            "blocked": dict(self._blocked),
        }
