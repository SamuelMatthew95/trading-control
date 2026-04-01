"""Tests for StrategyProposer — hypothesis filtering and proposal publishing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import StrategyProposer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


@pytest.fixture
def agent_state():
    return AgentStateRegistry()


@pytest.fixture
def strategy_proposer(mock_bus, mock_dlq, agent_state):
    return StrategyProposer(mock_bus, mock_dlq, agent_state=agent_state)


# ---------------------------------------------------------------------------
# Confidence filtering
# ---------------------------------------------------------------------------


async def test_filters_low_confidence_hypotheses(strategy_proposer, mock_bus):
    """Hypotheses below HYPOTHESIS_MIN_CONFIDENCE (default 0.7) must be ignored."""
    reflection_data = {
        "trace_id": "trace-001",
        "hypotheses": [
            {"description": "weak hypothesis", "confidence": 0.3, "type": "parameter"},
            {"description": "another weak", "confidence": 0.5, "type": "rule"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    # Nothing should be published to proposals or notifications
    for call in mock_bus.publish.call_args_list:
        stream = call[0][0]
        assert stream not in ("proposals", "notifications", "github_prs"), (
            f"Expected no publish but got publish to '{stream}' for low-confidence hypotheses"
        )


async def test_empty_hypotheses_publishes_nothing(strategy_proposer, mock_bus):
    """An empty hypotheses list must produce zero publishes."""
    reflection_data = {
        "trace_id": "trace-empty",
        "hypotheses": [],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    assert mock_bus.publish.call_count == 0


# ---------------------------------------------------------------------------
# Parameter change proposals
# ---------------------------------------------------------------------------


async def test_publishes_parameter_change_proposal(strategy_proposer, mock_bus):
    """A high-confidence 'parameter' hypothesis publishes to the proposals stream."""
    reflection_data = {
        "trace_id": "trace-param",
        "hypotheses": [
            {"description": "increase signal threshold", "confidence": 0.8, "type": "parameter"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    assert len(proposals_calls) == 1

    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "parameter_change"
    assert proposal["requires_approval"] is True
    assert proposal["content"]["implementation"] == "db_update"


# ---------------------------------------------------------------------------
# Rule change proposals
# ---------------------------------------------------------------------------


async def test_publishes_rule_change_proposal(strategy_proposer, mock_bus):
    """A high-confidence 'rule' hypothesis publishes to proposals AND github_prs."""
    reflection_data = {
        "trace_id": "trace-rule",
        "hypotheses": [
            {"description": "change entry rule", "confidence": 0.85, "type": "rule"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    github_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "github_prs"]

    assert len(proposals_calls) == 1
    assert len(github_calls) == 1

    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "code_change"
    assert proposal["content"]["implementation"] == "github_pr"


# ---------------------------------------------------------------------------
# Regime adjustment proposals
# ---------------------------------------------------------------------------


async def test_publishes_regime_adjustment_proposal(strategy_proposer, mock_bus):
    """A high-confidence 'regime' hypothesis produces a proposal_type='regime_adjustment'."""
    reflection_data = {
        "trace_id": "trace-regime",
        "regime_edge": {"current_regime": "risk_off", "recommendation": "reduce exposure"},
        "hypotheses": [
            {"description": "switch to defensive mode", "confidence": 0.8, "type": "regime"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    assert len(proposals_calls) == 1

    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "regime_adjustment"
    # regime_context should be populated from reflection regime_edge
    assert proposal["content"]["regime_context"]["current_regime"] == "risk_off"


# ---------------------------------------------------------------------------
# Notification per proposal
# ---------------------------------------------------------------------------


async def test_notification_published_per_proposal(strategy_proposer, mock_bus):
    """Each strong hypothesis that produces a proposal also publishes one notification."""
    reflection_data = {
        "trace_id": "trace-multi",
        "hypotheses": [
            {"description": "hypothesis one", "confidence": 0.75, "type": "parameter"},
            {"description": "hypothesis two", "confidence": 0.80, "type": "regime"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]

    assert len(proposals_calls) == 2
    assert len(notifications_calls) == 2
