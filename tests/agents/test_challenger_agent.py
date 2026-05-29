"""Regression tests for ChallengerAgent.

These cover the AttributeError that previously surfaced when a challenger ran
its first ``_grade()`` cycle: ``self._instance_id`` was referenced in the grade
and retirement payloads but never assigned in ``__init__``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import STREAM_AGENT_GRADES, STREAM_EXECUTIONS, STREAM_PROPOSALS
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


@pytest.mark.asyncio
async def test_challenger_registers_in_lifecycle(mock_bus, mock_dlq):
    """A running challenger with a strategy config appears in the registry at SHADOW."""
    from api.constants import StrategyStatus
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    agent = ChallengerAgent(
        mock_bus,
        mock_dlq,
        challenger_config={"strategy": "strong_only", "grade_every": 100},
        max_fills=100,
    )
    await agent.process(STREAM_EXECUTIONS, "1-0", {})

    registry = get_strategy_registry()
    match = [v for v in registry.versions() if v.config.get("strategy") == "strong_only"]
    assert len(match) == 1
    assert registry.status(match[0].version_id) == StrategyStatus.SHADOW


@pytest.mark.asyncio
async def test_challenger_without_strategy_does_not_register(mock_bus, mock_dlq):
    """A challenger with no strategy in its config registers nothing."""
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    agent = ChallengerAgent(mock_bus, mock_dlq, max_fills=100)
    await agent.process(STREAM_EXECUTIONS, "1-0", {})
    assert get_strategy_registry().versions() == []


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


def test_eager_shadow_registration_is_idempotent(mock_bus, mock_dlq):
    """Two challengers for the same strategy register exactly one SHADOW entry."""
    from api.constants import StrategyStatus
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    a = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"strategy": "strong_only"})
    b = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"strategy": "strong_only"})
    a._ensure_lifecycle_registered()
    b._ensure_lifecycle_registered()  # must not double-register

    reg = get_strategy_registry()
    matches = [v for v in reg.versions() if v.config.get("strategy") == "strong_only"]
    assert len(matches) == 1
    assert reg.status(matches[0].version_id) == StrategyStatus.SHADOW


@pytest.mark.asyncio
async def test_start_registers_shadow_eagerly(mock_bus, mock_dlq, monkeypatch):
    """start() registers the strategy at SHADOW before any fill arrives, so an
    auto-spawned shadow challenger shows on the lifecycle panel immediately."""
    from api.constants import StrategyStatus
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    agent = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"strategy": "confirmed_trend"})
    # Neutralize the base-class stream/consumer setup — assert only eager registration.
    monkeypatch.setattr(type(agent).__bases__[0], "start", AsyncMock())
    await agent.start()

    reg = get_strategy_registry()
    match = [v for v in reg.versions() if v.config.get("strategy") == "confirmed_trend"]
    assert len(match) == 1
    assert reg.status(match[0].version_id) == StrategyStatus.SHADOW
