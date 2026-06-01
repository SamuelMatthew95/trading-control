"""PROPOSAL ENGINE — the system architect. The ONLY interface that changes behaviour.

The Proposal Agent is a first-class agent (it registers like News/Tech/Macro).
It consumes the Learning Engine's *observations*, the current config, and its own
*success-rate history by proposal type*, and produces typed CANDIDATE changes. It
never edits a file or a weight — it emits a structured :class:`Proposal` whose
fate is decided downstream by the backtest gate (the judge) and the challenger
(the safety validator), and only ever applied by a merged Git PR.

A full :class:`ProposalType` hierarchy exists from day one (weights, prompts,
tools, backtest, risk, features) so the pipeline never has to be rewritten to
carry a new kind of change. The agent also LEARNS: a :class:`ProposalScorecard`
tracks how often each proposal type actually improved things, and that history
makes the agent stricter about kinds of change that have historically flopped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.config import WEIGHT_KEYS, CognitiveConfig, clamp_weight
from cognitive.events import EventType

try:  # Python 3.11+
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 fallback
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of StrEnum for Python 3.10."""


PROPOSAL_AGENT = "proposal_agent"
WEIGHT_STEP = 0.05
MIN_OBSERVATION_CONFIDENCE = 0.50
SCORECARD_PRIOR = 0.50  # success-rate assumed for a type with no history yet


class ProposalType(StrEnum):
    """Every kind of change the system can evolve through — fixed up front."""

    WEIGHT_CHANGE = "weight_change"
    PROMPT_CHANGE = "prompt_change"
    TOOL_CHANGE = "tool_change"
    BACKTEST_CHANGE = "backtest_change"
    RISK_CHANGE = "risk_change"
    FEATURE_CHANGE = "feature_change"


class ProposalStatus(StrEnum):
    """Lifecycle of a proposal through the evolution pipeline."""

    GENERATED = "generated"
    BACKTESTING = "backtesting"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"


@dataclass(frozen=True)
class Proposal:
    """A typed candidate change with full before/after diff visibility."""

    proposal_id: str
    proposal_type: str
    target: str
    old_value: Any = None
    new_value: Any = None
    change: Any = None
    reason: str = ""
    expected_impact: str = ""

    def diff(self) -> dict[str, dict[str, Any]]:
        """Full diff for the UI: ``{target: {"old": x, "new": y}}``."""
        return {self.target: {"old": self.old_value, "new": self.new_value}}

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.PROPOSAL.value,
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "target": self.target,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "change": self.change,
            "reason": self.reason,
            "expected_impact": self.expected_impact,
            "diff": self.diff(),
        }

    @classmethod
    def weight_change(
        cls,
        *,
        signal: str,
        old_value: float,
        new_value: float,
        reason: str,
        expected_impact: str = "",
        proposal_id: str | None = None,
    ) -> Proposal:
        target = f"weights.{signal}"
        return cls(
            proposal_id=proposal_id or f"P-{target}-{new_value}",
            proposal_type=ProposalType.WEIGHT_CHANGE.value,
            target=target,
            old_value=old_value,
            new_value=new_value,
            change=round(new_value - old_value, 6),
            reason=reason,
            expected_impact=expected_impact,
        )

    @classmethod
    def prompt_change(
        cls, *, target: str, new_value: str, reason: str, proposal_id: str | None = None
    ) -> Proposal:
        return cls(
            proposal_id=proposal_id or f"P-{target}",
            proposal_type=ProposalType.PROMPT_CHANGE.value,
            target=target,
            new_value=new_value,
            change=new_value,
            reason=reason,
        )

    @classmethod
    def tool_change(
        cls, *, target: str, action: str, reason: str, proposal_id: str | None = None
    ) -> Proposal:
        return cls(
            proposal_id=proposal_id or f"P-{target}-{action}",
            proposal_type=ProposalType.TOOL_CHANGE.value,
            target=target,
            new_value=action,
            change=action,
            reason=reason,
        )

    @classmethod
    def risk_change(
        cls,
        *,
        target: str,
        old_value: float,
        new_value: float,
        reason: str,
        proposal_id: str | None = None,
    ) -> Proposal:
        return cls(
            proposal_id=proposal_id or f"P-{target}-{new_value}",
            proposal_type=ProposalType.RISK_CHANGE.value,
            target=target,
            old_value=old_value,
            new_value=new_value,
            change=round(new_value - old_value, 6),
            reason=reason,
        )


@dataclass
class _TypeStat:
    """Mutable per-type success accumulator."""

    attempts: int = 0
    successes: int = 0


class ProposalScorecard:
    """Tracks proposal success-rate by type so the agent learns what works."""

    def __init__(self) -> None:
        self._stats: dict[str, _TypeStat] = {}

    def record(self, proposal_type: str, *, success: bool) -> None:
        stat = self._stats.setdefault(proposal_type, _TypeStat())
        stat.attempts += 1
        if success:
            stat.successes += 1

    def success_rate(self, proposal_type: str) -> float:
        stat = self._stats.get(proposal_type)
        if stat is None or stat.attempts == 0:
            return SCORECARD_PRIOR
        return round(stat.successes / stat.attempts, 4)

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {
            ptype: {
                "attempts": stat.attempts,
                "successes": stat.successes,
                "success_rate": self.success_rate(ptype),
            }
            for ptype, stat in self._stats.items()
        }


class ProposalAgent:
    """Generates typed candidate changes from observations. Applies nothing."""

    name = PROPOSAL_AGENT

    def __init__(
        self, *, step: float = WEIGHT_STEP, min_confidence: float = MIN_OBSERVATION_CONFIDENCE
    ) -> None:
        self.step = step
        self.min_confidence = min_confidence

    def propose(
        self,
        observations: list[Any],
        config: CognitiveConfig,
        scorecard: ProposalScorecard | None = None,
    ) -> Proposal | None:
        """Convert the strongest weight-relevant observation into a proposal.

        Success-rate history makes the agent self-correcting: if WEIGHT_CHANGE
        proposals have historically flopped, it demands higher confidence and
        takes a smaller step.
        """
        candidates = [obs for obs in observations if obs.signal in WEIGHT_KEYS]
        if not candidates:
            return None
        best = max(candidates, key=lambda obs: obs.confidence)

        rate = (
            scorecard.success_rate(ProposalType.WEIGHT_CHANGE.value)
            if scorecard is not None
            else SCORECARD_PRIOR
        )
        required_confidence = min(0.95, self.min_confidence + (1.0 - rate) * 0.3)
        if best.confidence < required_confidence:
            return None

        direction = 1 if best.direction == "outperforming" else -1
        step = self.step * (0.5 + 0.5 * rate)
        old_value = round(config.weights[best.signal], 6)
        new_value = round(clamp_weight(old_value + direction * step), 4)
        if new_value == old_value:
            return None

        evidence = best.evidence
        reason = (
            f"{best.signal} agent {best.direction} "
            f"(grade {evidence.get('agent_grade')}, correct_rate {evidence.get('correct_rate')}, "
            f"n={evidence.get('sample_size')})"
        )
        expected = (
            f"shift weights.{best.signal} {'up' if direction > 0 else 'down'} "
            f"by {abs(round(new_value - old_value, 4))} toward better-attributed signal"
        )
        return Proposal.weight_change(
            signal=best.signal,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            expected_impact=expected,
        )

    def emit(self, stream: Any, proposal: Proposal, *, trace_id: str = "") -> dict[str, Any]:
        payload = proposal.as_dict()
        stream.emit(EventType.PROPOSAL, payload, source=self.name, trace_id=trace_id)
        return payload


@dataclass
class QueueEntry:
    """One proposal's position in the evolution pipeline."""

    proposal: Proposal
    status: str
    verdict: dict[str, Any] | None = None
    delta: dict[str, Any] | None = None
    pull_request: dict[str, Any] | None = None
    proposal_grade: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.as_dict(),
            "status": self.status,
            "verdict": self.verdict,
            "delta": self.delta,
            "pull_request": self.pull_request,
            "proposal_grade": self.proposal_grade,
        }


class ProposalQueue:
    """The proposal lifecycle store that backs the UI's Evolution Center."""

    def __init__(self) -> None:
        self._entries: list[QueueEntry] = []

    def add(
        self, proposal: Proposal, *, status: str = ProposalStatus.GENERATED.value
    ) -> QueueEntry:
        entry = QueueEntry(proposal=proposal, status=status)
        self._entries.append(entry)
        return entry

    def update(self, proposal_id: str, **changes: Any) -> QueueEntry | None:
        for entry in self._entries:
            if entry.proposal.proposal_id == proposal_id:
                for key, value in changes.items():
                    setattr(entry, key, value)
                return entry
        return None

    def entries(self) -> list[QueueEntry]:
        return list(self._entries)

    def snapshot(self) -> list[dict[str, Any]]:
        return [entry.as_dict() for entry in self._entries]
