"""Tests for SystemArchitect — the deterministic high-level proposal synthesizer.

These lock in: it emits evidence-backed, fully-briefed strategic proposals from
accumulated state (per-model net ROI, grade trajectory); it does NOT fire on
sub-floor noise; it latches each observation so it never spams; and it honours
the enabled flag.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.config import settings
from api.constants import STREAM_PROPOSALS
from api.events.bus import EventBus
from api.services.agents.system_architect import SystemArchitect

pytestmark = pytest.mark.asyncio


class _FakeGrade:
    """Stand-in for the live GradeAgent — exposes the two buffers the architect
    reads (the eval buffer and the grade-score trajectory)."""

    def __init__(self, evals=None, scores=None) -> None:
        self._eval_buffer = list(evals or [])
        self._grade_score_history = deque((float(s), {}) for s in (scores or []))


def _make_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _proposals_published(bus: MagicMock) -> list[dict]:
    return [
        c.args[1] for c in bus.publish.call_args_list if c.args and c.args[0] == STREAM_PROPOSALS
    ]


def _losing_model_evals(model: str, n: int) -> list[dict]:
    return [
        {"model_used": model, "pnl": -3.0, "overall_score": 0.4, "decision_cost_usd": 0.001}
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# Model governance — the evidence-backed version of issue #341
# ---------------------------------------------------------------------------


async def test_emits_model_governance_proposal_for_net_negative_model():
    bus = _make_bus()
    architect = SystemArchitect(
        bus, None, grade_agent=_FakeGrade(evals=_losing_model_evals("gemini:flash", 6))
    )

    emitted = await architect.run_once()

    assert emitted >= 1
    proposals = _proposals_published(bus)
    governance = [p for p in proposals if "gemini:flash" in p["content"]["description"]]
    assert governance, "expected a model-governance proposal naming the losing model"
    proposal = governance[0]
    assert proposal["proposal_type"] == "code_change"
    brief = proposal["content"]["brief"]
    # The triage's "decide the mechanism" ask — disable / down-weight / fallback.
    assert "down-weight" in brief.lower()
    assert "fallback" in brief.lower()
    # Carries a Claude-Code-ready handoff.
    assert "Ready-to-paste Claude Code prompt" in brief


async def test_no_model_proposal_below_the_noise_floor():
    """One or two losing trades is noise (issue #341) — surface nothing at all."""
    bus = _make_bus()
    architect = SystemArchitect(
        bus, None, grade_agent=_FakeGrade(evals=_losing_model_evals("gemini:flash", 2))
    )

    await architect.run_once()

    proposals = _proposals_published(bus)
    assert not any("gemini:flash" in p["content"]["description"] for p in proposals)


# ---------------------------------------------------------------------------
# Sustained underperformance — a structural, design-level proposal
# ---------------------------------------------------------------------------


async def test_emits_structural_proposal_for_sustained_low_grades():
    bus = _make_bus()
    architect = SystemArchitect(bus, None, grade_agent=_FakeGrade(scores=[0.4] * 6))

    await architect.run_once()

    proposals = _proposals_published(bus)
    structural = [p for p in proposals if "structurally mis-fit" in p["content"]["description"]]
    assert structural, "expected a structural-underperformance proposal"
    assert structural[0]["proposal_type"] == "code_change"


async def test_no_structural_proposal_when_grades_are_healthy():
    bus = _make_bus()
    architect = SystemArchitect(bus, None, grade_agent=_FakeGrade(scores=[0.8] * 6))

    await architect.run_once()

    proposals = _proposals_published(bus)
    assert not any("structurally mis-fit" in p["content"]["description"] for p in proposals)


# ---------------------------------------------------------------------------
# Self-extension — the loop proposing a proposal type we didn't think of
# ---------------------------------------------------------------------------


async def test_emits_self_extension_proposal_for_a_recurring_costly_mistake():
    bus = _make_bus()
    evals = [{"mistakes": ["late_entry"], "pnl": -2.0} for _ in range(5)]
    architect = SystemArchitect(bus, None, grade_agent=_FakeGrade(evals=evals))

    await architect.run_once()

    proposals = _proposals_published(bus)
    selfext = [p for p in proposals if "late_entry" in p["content"]["description"]]
    assert selfext, "expected a self-extension proposal for the recurring mistake"
    proposal = selfext[0]
    assert proposal["proposal_type"] == "code_change"
    assert "extending the proposal taxonomy" in proposal["content"]["description"]
    # The brief points Claude Code at where to add the new observer.
    assert "system_architect.py" in proposal["content"]["brief"]


async def test_no_self_extension_for_a_one_off_mistake():
    """A single occurrence of a mistake is ordinary variance — not worth automating."""
    bus = _make_bus()
    evals = [{"mistakes": ["late_entry"], "pnl": -2.0}] + [
        {"mistakes": [], "pnl": 1.0} for _ in range(9)
    ]
    architect = SystemArchitect(bus, None, grade_agent=_FakeGrade(evals=evals))

    await architect.run_once()

    proposals = _proposals_published(bus)
    assert not any("late_entry" in p["content"]["description"] for p in proposals)


# ---------------------------------------------------------------------------
# Anti-spam + flag
# ---------------------------------------------------------------------------


async def test_observation_is_latched_and_not_re_emitted():
    bus = _make_bus()
    architect = SystemArchitect(
        bus, None, grade_agent=_FakeGrade(evals=_losing_model_evals("gemini:flash", 6))
    )

    first = await architect.run_once()
    second = await architect.run_once()

    assert first >= 1
    assert second == 0  # same observation — latched, never re-proposed


async def test_disabled_flag_emits_nothing(monkeypatch):
    monkeypatch.setattr(settings, "SYSTEM_ARCHITECT_ENABLED", False)
    bus = _make_bus()
    architect = SystemArchitect(
        bus, None, grade_agent=_FakeGrade(evals=_losing_model_evals("gemini:flash", 6))
    )

    assert await architect.run_once() == 0
    assert not _proposals_published(bus)
