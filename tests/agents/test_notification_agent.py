"""Tests for NotificationAgent — severity classification and deduplication."""

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest

from api.constants import NOTIFICATIONS_STREAM_MAXLEN
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
    """The same stream+type+trace combination within the dedup window is forwarded only once."""
    event = {
        "type": "order_filled",
        "side": "buy",
        "symbol": "BTC/USD",
        "qty": 1,
        "price": 100.0,
        "trace_id": "trace-dedup-test",  # same trace = same dedup key regardless of msg id
    }

    await notification_agent.process("executions", "id-1", event)
    await notification_agent.process("executions", "id-2", event)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 1


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_deduplication_allows_different_event_types(notification_agent, mock_bus):
    """Two events with different types on the same stream are both forwarded."""
    event_a = {"type": "order_filled", "side": "buy", "symbol": "BTC/USD"}
    event_b = {"type": "order_filled", "side": "sell", "symbol": "BTC/USD"}

    await notification_agent.process("executions", "id-1", event_a)
    await notification_agent.process("executions", "id-2", event_b)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 2


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_deduplication_allows_same_event_type_different_symbol(notification_agent, mock_bus):
    """Same type should not dedup away distinct symbols."""
    event_a = {"type": "order_filled", "side": "buy", "symbol": "AAPL"}
    event_b = {"type": "order_filled", "side": "buy", "symbol": "TSLA"}

    await notification_agent.process("executions", "id-1", event_a)
    await notification_agent.process("executions", "id-2", event_b)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 2


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_deduplication_uses_redis_id_when_trace_missing(notification_agent, mock_bus):
    """Events without trace_id/msg_id should dedup by redis_id, not collapse by side+symbol."""
    event = {"type": "order_filled", "side": "buy", "symbol": "BTC/USD"}

    await notification_agent.process("executions", "id-1", event)
    await notification_agent.process("executions", "id-2", event)

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
    """A valid buy/sell execution event is forwarded to the 'notifications' stream."""
    event = {
        "type": "order_filled",
        "side": "buy",
        "symbol": "BTC/USD",
        "qty": 1,
        "price": 100.0,
    }

    await notification_agent.process("executions", "id-1", event)

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 1

    notification = notifications_calls[0][0][1]
    assert notifications_calls[0][1]["maxlen"] == NOTIFICATIONS_STREAM_MAXLEN
    assert notification["severity"] == "INFO"
    assert notification["source"] == "notification_agent"
    assert "BTC/USD" in notification["message"]


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_buy_execution_notification_is_trade_ready(notification_agent, mock_bus):
    """Buy fills carry clear trade fields plus channel-specific delivery copy."""
    event = {
        "type": "order_filled",
        "side": "buy",
        "symbol": "BTC/USD",
        "qty": 0.25,
        "price": 50000.0,
        "fill_price": 50100.0,
        "order_id": "ord-1",
        "trace_id": "trace-buy",
    }

    await notification_agent.process("executions", "id-buy", event)

    notification = next(
        c[0][1] for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"
    )
    assert notification["notification_type"] == "trade.buy_filled"
    assert notification["title"] == "BUY filled: BTC/USD"
    assert notification["action"] == "buy"
    assert notification["symbol"] == "BTC/USD"
    assert notification["qty"] == 0.25
    assert notification["fill_price"] == 50100.0
    assert notification["notional"] == 12525.0
    assert notification["trace_id"] == "trace-buy"
    assert notification["metadata"]["trade"]["stop_price"] == 47595.0
    assert notification["metadata"]["trade"]["take_profit_price"] == 55110.0
    assert notification["delivery"]["template"] == "trade_execution"
    assert notification["delivery"]["slack"]["blocks"][0]["text"]["text"] == "BUY filled: BTC/USD"
    assert notification["delivery"]["email"]["subject"] == "BUY filled: BTC/USD"
    assert "BUY BTC/USD filled" in notification["delivery"]["telegram"]["text"]
    assert notification["display"]["kind"] == "trade_execution"
    assert notification["display"]["tone"] == "buy"
    assert notification["display"]["icon"] == "arrow-up-right"
    assert notification["display"]["title"] == "BUY filled: BTC/USD"
    assert notification["display"]["badges"] == [{"label": "BUY", "tone": "buy"}]
    display_facts = {item["label"]: item["value"] for item in notification["display"]["facts"]}
    assert display_facts["Qty"] == "0.25"
    assert display_facts["Fill"] == "$50,100.00"
    assert display_facts["Notional"] == "$12,525.00"
    assert display_facts["Stop"] == "$47,595.00"
    assert display_facts["Target"] == "$55,110.00"


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_sell_execution_notification_shows_realized_pnl(notification_agent, mock_bus):
    """Sell fills are visibly distinct and include realized PnL when available."""
    event = {
        "type": "order_filled",
        "side": "sell",
        "symbol": "AAPL",
        "qty": 5,
        "fill_price": 188.25,
        "pnl": -12.5,
        "pnl_percent": -1.32,
        "order_id": "ord-2",
        "trace_id": "trace-sell",
    }

    await notification_agent.process("executions", "id-sell", event)

    notification = next(
        c[0][1] for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"
    )
    assert notification["severity"] == "WARNING"
    assert notification["notification_type"] == "trade.sell_filled"
    assert notification["title"] == "SELL filled: AAPL"
    assert notification["action"] == "sell"
    assert notification["notional"] == 941.25
    assert "Proceeds $941.25" in notification["message"]
    assert "Realized PnL -$12.50 (-1.32%)" in notification["message"]
    assert notification["display"]["tone"] == "sell"
    assert notification["display"]["icon"] == "arrow-down-right"
    display_facts = {item["label"]: item for item in notification["display"]["facts"]}
    assert display_facts["Proceeds"]["value"] == "$941.25"
    assert display_facts["P&L"]["value"] == "-$12.50 (-1.32%)"
    assert display_facts["P&L"]["tone"] == "loss"


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_non_execution_streams_do_not_publish(notification_agent, mock_bus):
    """Signals, grades, proposals, and risk alerts must NOT surface as user notifications."""
    await notification_agent.process("signals", "id-1", {"symbol": "BTC/USD"})
    await notification_agent.process("agent_grades", "id-2", {"grade": "F", "symbol": "AAPL"})
    await notification_agent.process("risk_alerts", "id-3", {"symbol": "TSLA"})
    await notification_agent.process("proposals", "id-4", {"symbol": "NVDA"})

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert notifications_calls == []


@pytest.mark.asyncio
@patch(
    "api.core.writer.safe_writer.SafeWriter",
    MagicMock(return_value=MagicMock(write_notification=AsyncMock())),
)
async def test_execution_without_buy_or_sell_side_is_dropped(notification_agent, mock_bus):
    """Execution events missing or carrying a non-buy/sell side must not publish."""
    await notification_agent.process(
        "executions", "id-1", {"type": "order_filled", "symbol": "BTC/USD"}
    )
    await notification_agent.process(
        "executions", "id-2", {"type": "order_filled", "side": "hold", "symbol": "BTC/USD"}
    )

    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert notifications_calls == []


@pytest.mark.asyncio
async def test_in_memory_fallback_records_trade_notification(notification_agent, mock_bus):
    """When the DB is unavailable, trade fills must still hydrate the dashboard.

    Regression for: notifications only appearing on the live WebSocket and
    vanishing on page reload because the in-memory store had no record of them.
    """
    from api.runtime_state import get_runtime_store

    # Conftest's autouse fixture already sets is_db_available() to False, so
    # the agent should route the persist through InMemoryStore.record_notification
    # instead of SafeWriter.
    event = {
        "type": "order_filled",
        "side": "buy",
        "symbol": "BTC/USD",
        "qty": 0.5,
        "price": 43000.0,
        "fill_price": 43050.0,
        "trace_id": "trace-mem-1",
    }

    await notification_agent.process("executions", "id-mem-1", event)

    snapshot = get_runtime_store().dashboard_fallback_snapshot()
    notifications = snapshot["notifications"]
    assert len(notifications) == 1
    n = notifications[0]
    assert n["notification_type"] == "trade.buy_filled"
    assert n["symbol"] == "BTC/USD"
    assert n["action"] == "buy"
    assert n["fill_price"] == 43050.0

    # The bus broadcast still fires so live subscribers see the fill too.
    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]
    assert len(notifications_calls) == 1
