"""Regression tests for ChallengerAgent.

These cover the AttributeError that previously surfaced when a challenger ran
its first ``_grade()`` cycle: ``self._instance_id`` was referenced in the grade
and retirement payloads but never assigned in ``__init__``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import STREAM_AGENT_GRADES, STREAM_PROPOSALS
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.pipeline_agents import ChallengerAgent


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


def test_challenger_assigns_instance_id_in_init(mock_bus, mock_dlq):
    """instance_id must be set so grade/retire payloads can reference it."""
    agent = ChallengerAgent(mock_bus, mock_dlq, max_fills=5)
    assert agent._instance_id is not None
    assert agent._instance_id == agent._challenger_id


@pytest.mark.asyncio
async def test_grade_publishes_payload_with_instance_id(mock_bus, mock_dlq):
    """_grade() previously raised AttributeError on self._instance_id."""
    agent = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"grade_every": 1}, max_fills=100)
    # Seed enough fills to trigger _grade() exactly once.
    await agent.process("trade_performance", "1-0", {"pnl": 1.5})

    # _grade() runs because fills=1 % grade_every=1 == 0
    publish_calls = mock_bus.publish.await_args_list
    assert publish_calls, "expected at least one publish from _grade()"
    stream, payload = publish_calls[0].args
    assert stream == STREAM_AGENT_GRADES
    # instance_id is nested in the metrics block alongside challenger_id.
    assert payload["metrics"]["instance_id"] == agent._challenger_id


@pytest.mark.asyncio
async def test_retire_summary_includes_instance_id(mock_bus, mock_dlq):
    """_retire_with_summary() also references self._instance_id."""
    agent = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"grade_every": 100}, max_fills=1)
    # Force stop() to be a no-op so we can inspect publish calls.
    agent.stop = AsyncMock()  # type: ignore[method-assign]

    await agent.process("trade_performance", "1-0", {"pnl": 0.5})

    proposal_calls = [
        call for call in mock_bus.publish.await_args_list if call.args[0] == STREAM_PROPOSALS
    ]
    assert proposal_calls, "expected challenger to publish a retirement proposal"
    payload = proposal_calls[0].args[1]
    assert payload["instance_id"] == agent._challenger_id
