"""Tests for NotificationAgent — severity classification and deduplication."""

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import NotificationAgent

# Async mark applied per async function; sync classify tests do not carry this mark.


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
async def fake_redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def notification_agent(mock_bus, mock_dlq, agent_state, fake_redis):
    return NotificationAgent(mock_bus, mock_dlq, fake_redis, agent_state=agent_state)


# ---------------------------------------------------------------------------
# _classify_severity unit tests (pure logic, no async needed)
# ---------------------------------------------------------------------------


def test_classify_severity_critical_for_grade_f(notification_agent):
    """Grade F events on agent_grades stream must be classified as CRITICAL."""
    severity = notification_agent._classify_severity("agent_grades", {"grade": "F"})
    assert severity == "CRITICAL"


def test_classify_severity_urgent_for_grade_d(notification_agent):
    """Grade D events on agent_grades stream must be classified as URGENT."""
    severity = notification_agent._classify_severity("agent_grades", {"grade": "D"})
    assert severity == "URGENT"


def test_classify_severity_urgent_for_risk_alerts(notification_agent):
    """risk_alerts stream always maps to URGENT severity."""
    severity = notification_agent._classify_severity("risk_alerts", {})
    assert severity == "URGENT"


def test_classify_severity_info_default(notification_agent):
    """Unknown or INFO streams fall back to INFO severity."""
    severity = notification_agent._classify_severity("signals", {})
    assert severity == "INFO"


def test_classify_severity_inherits_explicit(notification_agent):
    """If the event payload carries an explicit 'severity', that value is returned as-is."""
    severity = notification_agent._classify_severity("signals", {"severity": "WARNING"})
    assert severity == "WARNING"


def test_classify_severity_explicit_overrides_grade(notification_agent):
    """An explicit severity field takes precedence even over grade-based logic."""
    # Payload has grade=F but also explicit severity=INFO — explicit wins
    severity = notification_agent._classify_severity(
        "agent_grades", {"grade": "F", "severity": "INFO"}
    )
    assert severity == "INFO"


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_deduplication_skips_repeat(notification_agent, mock_bus):
    """The same stream+type combination within the dedup window is forwarded only once."""
    event = {"type": "agent_grade", "grade": "B", "score": 0.72}

    await notification_agent.process("agent_grades", "id-1", event)
    await notification_agent.process("agent_grades", "id-2", event)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 1


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_deduplication_allows_different_event_types(notification_agent, mock_bus):
    """Two events with different types on the same stream are both forwarded."""
    event_a = {"type": "agent_grade", "grade": "A"}
    event_b = {"type": "agent_suspension", "reason": "low grades"}

    await notification_agent.process("agent_grades", "id-1", event_a)
    await notification_agent.process("agent_grades", "id-2", event_b)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 2


# ---------------------------------------------------------------------------
# Skip-self-stream test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_notifications_stream(notification_agent, mock_bus):
    """Events arriving on the 'notifications' stream must be silently ignored."""
    await notification_agent.process(
        "notifications",
        "id-1",
        {"type": "notification", "severity": "INFO", "message": "test"},
    )

    assert mock_bus.publish.call_count == 0


# ---------------------------------------------------------------------------
# Happy-path forwarding test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_publishes_to_notifications_stream(notification_agent, mock_bus):
    """A valid, non-duplicate event must be forwarded to the 'notifications' stream."""
    event = {"type": "signal", "symbol": "BTC/USD", "direction": "bullish"}

    await notification_agent.process("signals", "id-1", event)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 1

    notification = notifications_calls[0][0][1]
    assert notification["severity"] == "INFO"
    assert notification["source"] == "notification_agent"
