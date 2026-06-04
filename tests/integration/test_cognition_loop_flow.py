"""End-to-end proof that the learning cognition loop is connected and flowing.

Each stage is unit-tested in isolation (test_grade_agent, test_reflection_agent,
test_strategy_proposer, test_proposal_applier covers every routing branch). What
was missing — and what this file adds — is proof that the REAL agents hand off to
each other without producer/consumer drift, i.e. the loop does not silently go
"dead" between stages:

    trade fills + grades ─► ReflectionAgent ──► reflection_outputs   (learnings flow)
    reflection_outputs    ─► StrategyProposer ─► proposals           (proposals happen, many types)
    each proposal         ─► ProposalApplier  ─► recognised + routed (every type is acted on)

The only mocked dependencies are the two external ones — the LLM and Redis.
Agents, payload shapes, the creation guardrail, and routing are all real, so a
renamed field or a dropped stream between producer and consumer fails these.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from api.config import settings
from api.constants import (
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    FieldName,
    LogType,
    ProposalType,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import ReflectionAgent, StrategyProposer
from api.services.agents.proposal_applier import ProposalApplier

pytestmark = pytest.mark.asyncio

# Hypotheses spanning the four types StrategyProposer._build_proposal maps:
#   parameter → PARAMETER_CHANGE, rule → CODE_CHANGE,
#   new_agent → NEW_AGENT, anything else (regime) → REGIME_ADJUSTMENT.
_HYPOTHESES = [
    {"description": "raise RSI entry threshold to 35", "confidence": 0.92, "type": "parameter"},
    {"description": "rewrite breakout confirmation rule", "confidence": 0.85, "type": "rule"},
    {"description": "spawn a mean-reversion challenger", "confidence": 0.80, "type": "new_agent"},
    {"description": "de-risk in a high-volatility regime", "confidence": 0.75, "type": "regime"},
]
_REFLECTION_JSON = json.dumps(
    {
        "summary": "losing on late entries; tighten filters",
        "winning_factors": ["rsi"],
        "losing_factors": ["chasing"],
        "hypotheses": _HYPOTHESES,
    }
)
_EXPECTED_TYPES = {
    ProposalType.PARAMETER_CHANGE,
    ProposalType.CODE_CHANGE,
    ProposalType.NEW_AGENT,
    ProposalType.REGIME_ADJUSTMENT,
}
# Types whose content from a reflection hypothesis is actionable at the applier
# (they file a GitHub issue / artifact). A reflection-born PARAMETER_CHANGE is
# description-only — there is no concrete value to auto-PR — so it is correctly a
# recognised no-op that lives in the human review queue, not an auto-apply.
_ACTIONABLE_TYPES = {
    ProposalType.CODE_CHANGE,
    ProposalType.NEW_AGENT,
    ProposalType.REGIME_ADJUSTMENT,
}


def _recording_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


def _published(bus: MagicMock, stream: str) -> list[dict]:
    return [c.args[1] for c in bus.publish.await_args_list if c.args and c.args[0] == stream]


@pytest.fixture
def dlq() -> MagicMock:
    d = MagicMock(spec=DLQManager)
    d.push = AsyncMock()
    return d


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _patch_loop_io(monkeypatch, fake_redis):
    """Mock only the loop's two external dependencies — the LLM and Redis."""
    monkeypatch.setattr(
        "api.services.llm_router.call_llm_with_system",
        AsyncMock(return_value=(_REFLECTION_JSON, 100, 0.0001)),
    )
    monkeypatch.setattr("api.redis_client.get_redis", AsyncMock(return_value=fake_redis))
    # Keep prompt-evolution out of this flow so the only proposals are the four
    # hypothesis-derived ones (prompt-evolution routing is covered elsewhere).
    monkeypatch.setattr(settings, "PROMPT_EVOLUTION_ENABLED", False)
    monkeypatch.setattr(settings, "REFLECT_EVERY_N_FILLS", 3)


def _reflection_outputs_payload() -> dict:
    return {FieldName.TRACE_ID: "refl-1", FieldName.HYPOTHESES: _HYPOTHESES}


async def _emit_proposals(dlq) -> list[dict]:
    """Run the REAL StrategyProposer on a reflection output and return its proposals."""
    bus = _recording_bus()
    proposer = StrategyProposer(bus, dlq, agent_state=AgentStateRegistry())
    await proposer.process("reflection_outputs", "refl-1", _reflection_outputs_payload())
    return _published(bus, STREAM_PROPOSALS)


# ---------------------------------------------------------------------------
# Stage handoffs
# ---------------------------------------------------------------------------


async def test_reflection_consumes_grades_and_fills_then_emits_hypotheses(dlq):
    """fills (+ a grade as context) trigger a reflection that carries hypotheses."""
    bus = _recording_bus()
    reflector = ReflectionAgent(bus, dlq, agent_state=AgentStateRegistry())

    # A grade is consumed as reflection context; three fills cross the trigger.
    await reflector.process("agent_grades", "g-1", {FieldName.GRADE: "C", FieldName.SCORE: 0.4})
    for i in range(3):
        await reflector.process(
            "trade_performance",
            f"f-{i}",
            {
                FieldName.PNL: float(i - 1),
                FieldName.PNL_PERCENT: 0.5,
                FieldName.SYMBOL: "BTC/USD",
                FieldName.SIDE: "buy",
            },
        )

    reflections = _published(bus, STREAM_REFLECTION_OUTPUTS)
    assert reflections, "ReflectionAgent never published reflection_outputs from fills"
    assert reflections[-1].get(FieldName.HYPOTHESES), (
        "reflection carried no hypotheses for the proposer"
    )


async def test_strategy_proposer_emits_a_proposal_for_every_hypothesis_type(dlq):
    """reflection_outputs with four hypothesis types → four distinctly-typed proposals."""
    proposals = await _emit_proposals(dlq)
    types = {p.get(FieldName.PROPOSAL_TYPE) for p in proposals}
    assert types == _EXPECTED_TYPES, f"missing proposal types: {_EXPECTED_TYPES - types}"


async def test_applier_recognises_and_acts_on_every_emitted_proposal(dlq, fake_redis, monkeypatch):
    """Every proposal the proposer emits is routed (no dead types); actionable ones apply."""
    applied_log = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", applied_log)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())

    proposals = await _emit_proposals(dlq)
    assert proposals, "proposer emitted nothing to route"

    applier = ProposalApplier(_recording_bus(), dlq, fake_redis, agent_state=AgentStateRegistry())
    # Every emitted type must have a handler — none falls through to "unknown".
    for proposal in proposals:
        assert applier._handlers.get(proposal.get(FieldName.PROPOSAL_TYPE)) is not None

    for i, proposal in enumerate(proposals):
        await applier.process("proposals", f"{i}-0", proposal)

    applied_types = {
        call.args[2].get(FieldName.PROPOSAL_TYPE)
        for call in applied_log.await_args_list
        if len(call.args) >= 3 and call.args[1] == LogType.PROPOSAL
    }
    assert _ACTIONABLE_TYPES <= applied_types, (
        f"types not routed to an action: {_ACTIONABLE_TYPES - applied_types}"
    )


# ---------------------------------------------------------------------------
# Full loop
# ---------------------------------------------------------------------------


async def test_full_cognition_loop_reflection_to_proposals_to_apply(dlq, fake_redis, monkeypatch):
    """Drive the whole chain with real agents: fills → reflection → proposals → routed.

    A break at any handoff (reflection emits no hypotheses, proposer reads the
    wrong key, applier doesn't recognise a type) fails this single test.
    """
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())

    # 1. Reflection from fills.
    reflect_bus = _recording_bus()
    reflector = ReflectionAgent(reflect_bus, dlq, agent_state=AgentStateRegistry())
    for i in range(3):
        await reflector.process(
            "trade_performance",
            f"f-{i}",
            {
                FieldName.PNL: float(i - 1),
                FieldName.PNL_PERCENT: 0.5,
                FieldName.SYMBOL: "BTC/USD",
                FieldName.SIDE: "buy",
            },
        )
    reflections = _published(reflect_bus, STREAM_REFLECTION_OUTPUTS)
    assert reflections, "loop broke at reflection: no reflection_outputs"

    # 2. Proposer consumes the REAL reflection output (not a crafted one).
    proposer_bus = _recording_bus()
    proposer = StrategyProposer(proposer_bus, dlq, agent_state=AgentStateRegistry())
    await proposer.process("reflection_outputs", "loop", reflections[-1])
    proposals = _published(proposer_bus, STREAM_PROPOSALS)
    assert proposals, "loop broke at proposer: reflection produced no proposals"
    assert len({p.get(FieldName.PROPOSAL_TYPE) for p in proposals}) >= 2, (
        "expected multiple proposal types"
    )

    # 3. Applier routes each proposal — none falls through as an unknown type.
    applier = ProposalApplier(_recording_bus(), dlq, fake_redis, agent_state=AgentStateRegistry())
    for i, proposal in enumerate(proposals):
        assert applier._handlers.get(proposal.get(FieldName.PROPOSAL_TYPE)) is not None, (
            f"loop broke at applier: unroutable type {proposal.get(FieldName.PROPOSAL_TYPE)}"
        )
        await applier.process("proposals", f"{i}-0", proposal)
