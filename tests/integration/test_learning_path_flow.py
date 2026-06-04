"""End-to-end proof that the FRONT of the learning loop is alive.

``test_cognition_loop_flow.py`` proves the back half (reflection -> proposals ->
apply). What was missing — and what an operator sees as a dashboard stuck on
"Latest Grade --" while the board looks dead — is proof that a closed TRADE
actually produces a GRADE, that the same trade stream yields BOTH a grade and a
routed proposal, and that a decision's tools are credited with the trade's
realized PnL (the outcome -> tool-alpha loop behind tool governance).

These run the REAL GradeAgent / ReflectionAgent / StrategyProposer /
ProposalApplier, so a renamed field or a dropped stream between any producer and
consumer fails the test. Only the two external dependencies are mocked — the LLM
and Redis — plus grade persistence, which is spied so the assertions are about
the agents' handoffs, not the DB.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from api.config import settings
from api.constants import (
    STREAM_AGENT_GRADES,
    STREAM_DECISIONS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    LogType,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import GradeAgent, ReflectionAgent, StrategyProposer
from api.services.agents.proposal_applier import ProposalApplier
from api.services.tool_registry import get_tool_registry, set_tool_registry

pytestmark = pytest.mark.asyncio

# Four hypothesis types so StrategyProposer emits PARAMETER/CODE/NEW_AGENT/REGIME.
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


def _recording_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


def _published(bus: MagicMock, stream: str) -> list[dict]:
    return [c.args[1] for c in bus.publish.await_args_list if c.args and c.args[0] == stream]


def _trade(i: int) -> dict:
    """A closed-trade event; pnl spans negative/zero/positive across i=0,1,2."""
    return {
        FieldName.PNL: float(i - 1),
        FieldName.PNL_PERCENT: 0.5,
        FieldName.SYMBOL: "BTC/USD",
        FieldName.SIDE: "buy",
        FieldName.TRACE_ID: f"trade-{i}",
    }


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
    """Mock only the loop's two external dependencies — the LLM and Redis — and
    pin the fill triggers low so a handful of trades exercises the whole chain."""
    monkeypatch.setattr(
        "api.services.llm_router.call_llm_with_system",
        AsyncMock(return_value=(_REFLECTION_JSON, 100, 0.0001)),
    )
    monkeypatch.setattr("api.redis_client.get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(settings, "PROMPT_EVOLUTION_ENABLED", False)
    monkeypatch.setattr(settings, "REFLECT_EVERY_N_FILLS", 3)
    monkeypatch.setattr(settings, "GRADE_EVERY_N_FILLS", 1)
    # Persistence is spied, not exercised — assertions are about agent handoffs.
    monkeypatch.setattr("api.services.agents.pipeline_agents.write_grade_to_db", AsyncMock())
    monkeypatch.setattr("api.services.agents.pipeline_agents.persist_trade_evaluation", AsyncMock())


async def test_closed_trade_produces_a_grade(dlq, monkeypatch):
    """A single closed trade drives GradeAgent to PUBLISH a grade and LOG it — the
    exact link behind a dashboard stuck on 'Latest Grade --' on an idle board."""
    log_spy = AsyncMock()
    monkeypatch.setattr("api.services.agents.pipeline_agents.write_agent_log", log_spy)

    bus = _recording_bus()
    grader = GradeAgent(bus, dlq, agent_state=AgentStateRegistry())
    await grader.process(STREAM_TRADE_PERFORMANCE, "f-1", _trade(2))  # pnl=+1.0

    grades = _published(bus, STREAM_AGENT_GRADES)
    assert grades, "no grade published — the trade->grade link is dead"
    assert grades[-1].get(FieldName.GRADE) in {"A", "B", "C", "D", "F"}
    assert grades[-1].get(FieldName.SCORE) is not None

    logged = [c for c in log_spy.await_args_list if len(c.args) >= 2 and c.args[1] == LogType.GRADE]
    assert logged, "grade not written to agent_logs (the learning panel would stay empty)"


async def test_trade_stream_yields_both_a_grade_and_a_routed_proposal(dlq, fake_redis, monkeypatch):
    """One trade stream, real agents: GradeAgent emits a grade AND the same fills
    drive ReflectionAgent -> StrategyProposer -> ProposalApplier to a routed
    proposal. A break at any handoff fails this single test."""
    monkeypatch.setattr("api.services.agents.pipeline_agents.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())

    grade_bus = _recording_bus()
    reflect_bus = _recording_bus()
    grader = GradeAgent(grade_bus, dlq, agent_state=AgentStateRegistry())
    reflector = ReflectionAgent(reflect_bus, dlq, agent_state=AgentStateRegistry())

    # One trade stream feeds BOTH the grader and the reflector.
    for i in range(3):
        trade = _trade(i)
        await grader.process(STREAM_TRADE_PERFORMANCE, f"f-{i}", trade)
        await reflector.process(STREAM_TRADE_PERFORMANCE, f"f-{i}", trade)

    # 1. A grade came out of the trades.
    assert _published(grade_bus, STREAM_AGENT_GRADES), "loop broke: trades produced no grade"

    # 2. Reflection turned the fills into hypotheses.
    reflections = _published(reflect_bus, STREAM_REFLECTION_OUTPUTS)
    assert reflections, "loop broke at reflection: no reflection_outputs"

    # 3. The proposer turns the REAL reflection output into proposals.
    proposer_bus = _recording_bus()
    proposer = StrategyProposer(proposer_bus, dlq, agent_state=AgentStateRegistry())
    await proposer.process(STREAM_REFLECTION_OUTPUTS, "loop", reflections[-1])
    proposals = _published(proposer_bus, STREAM_PROPOSALS)
    assert proposals, "loop broke at proposer: reflection produced no proposals"

    # 4. Every proposal routes — none falls through as an unknown type.
    applier = ProposalApplier(_recording_bus(), dlq, fake_redis, agent_state=AgentStateRegistry())
    for i, proposal in enumerate(proposals):
        assert applier._handlers.get(proposal.get(FieldName.PROPOSAL_TYPE)) is not None, (
            f"loop broke at applier: unroutable type {proposal.get(FieldName.PROPOSAL_TYPE)}"
        )
        await applier.process("proposals", f"{i}-0", proposal)


async def test_realized_pnl_attributes_to_the_decision_tools(dlq, monkeypatch):
    """The decisions->grade handoff: a decision names the tools that informed it;
    when the matching trade closes, GradeAgent folds the realized PnL into those
    tools' alpha — the outcome->tool-alpha loop behind tool governance."""
    monkeypatch.setattr("api.services.agents.pipeline_agents.write_agent_log", AsyncMock())

    # Fresh registry (re-seeds the default catalog lazily) so we never perturb
    # other tests; the original singleton is restored in finally.
    original = get_tool_registry()
    set_tool_registry(None)
    try:
        registry = get_tool_registry()
        tool = registry.attribution()[0]  # an actually-seeded tool
        tool_name, before_count, before_alpha = tool.name, tool.call_count, tool.alpha_score

        bus = _recording_bus()
        grader = GradeAgent(bus, dlq, agent_state=AgentStateRegistry())
        # 1. A decision announces which tools informed it.
        await grader.process(
            STREAM_DECISIONS,
            "d-1",
            {FieldName.TRACE_ID: "t-1", FieldName.TOOLS_USED: [{FieldName.NAME: tool_name}]},
        )
        # 2. The matching trade closes with a clear realized profit.
        await grader.process(
            STREAM_TRADE_PERFORMANCE,
            "f-1",
            {
                FieldName.TRACE_ID: "t-1",
                FieldName.PNL: 250.0,
                FieldName.SYMBOL: "BTC/USD",
                FieldName.SIDE: "buy",
            },
        )

        graded = next(t for t in get_tool_registry().attribution() if t.name == tool_name)
        assert graded.call_count == before_count + 1, "decision tool was not credited the trade"
        assert graded.alpha_score > before_alpha, "+250 PnL did not pull the tool's alpha up"
    finally:
        set_tool_registry(original)
