"""End-to-end coverage of the buy/sell notification in-memory pipeline.

Exercises the contract documented in CLAUDE.md / memory-storage.md:

  ExecutionEngine → STREAM_EXECUTIONS
        ↓
  NotificationAgent.process(STREAM_EXECUTIONS, ...)
        ├─ records to InMemoryStore.notifications  (canonical UI buffer)
        ├─ publishes to STREAM_NOTIFICATIONS       (live WS feed)
        └─ best-effort DB write (audit only, skipped when DB is down)

Plus the API surface that the dashboard relies on:

  GET  /dashboard/state         → returns InMemoryStore.notifications
  GET  /dashboard/notifications → standalone listing of the buffer
  POST /dashboard/notifications/clear → empties the buffer
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.routes import dashboard_v2
from api.runtime_state import (
    get_runtime_store,
    set_db_available,
    set_runtime_store,
)
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import NotificationAgent


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
async def fake_redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def fresh_store():
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)  # exercise the in-memory path
    return store


@pytest.fixture
def agent(mock_bus, mock_dlq, fake_redis, fresh_store):
    return NotificationAgent(
        mock_bus, mock_dlq, fake_redis, agent_state=AgentStateRegistry()
    )


# ---------------------------------------------------------------------------
# InMemoryStore.record_notification — shape + dedup + cap
# ---------------------------------------------------------------------------


def test_record_notification_normalizes_canonical_shape(fresh_store):
    record = fresh_store.record_notification(
        {
            "msg_id": "abc-123",
            "message": "BUY FILLED — BTC/USD",
            "severity": "INFO",
            "notification_type": "execution.buy",
            "stream_source": "executions",
        }
    )
    assert record is not None
    assert record["id"] == "abc-123"
    assert record["msg_id"] == "abc-123"
    assert record["severity"] == "INFO"
    assert record["state"] == "open"
    # Timestamp is ISO-formatted for direct frontend consumption
    assert "T" in record["timestamp"] and record["timestamp"].endswith("+00:00")


def test_record_notification_is_idempotent_on_msg_id(fresh_store):
    payload = {"msg_id": "dup-1", "message": "BUY FILLED — BTC/USD"}
    first = fresh_store.record_notification(payload)
    second = fresh_store.record_notification(payload)
    assert first is not None
    assert second is None
    assert len(fresh_store.notifications) == 1


def test_record_notification_buffer_capped_at_100(fresh_store):
    for i in range(150):
        fresh_store.record_notification({"msg_id": f"id-{i}", "message": f"msg-{i}"})
    assert len(fresh_store.notifications) == 100
    # Oldest entries evicted; newest retained
    assert fresh_store.notifications[0]["msg_id"] == "id-50"
    assert fresh_store.notifications[-1]["msg_id"] == "id-149"


def test_clear_notifications_returns_count_and_empties(fresh_store):
    fresh_store.record_notification({"msg_id": "a", "message": "x"})
    fresh_store.record_notification({"msg_id": "b", "message": "y"})
    cleared = fresh_store.clear_notifications()
    assert cleared == 2
    assert fresh_store.notifications == []


def test_legacy_add_notification_normalizes_to_severity(fresh_store):
    fresh_store.add_notification("DB down", level="warning", notification_type="startup")
    assert len(fresh_store.notifications) == 1
    n = fresh_store.notifications[0]
    assert n["severity"] == "WARNING"
    assert n["notification_type"] == "startup"
    # Legacy callers don't supply msg_id; we still produce a stable id
    assert n["id"]


# ---------------------------------------------------------------------------
# NotificationAgent — records to InMemoryStore on every emit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buy_fill_lands_in_memory_store(agent, mock_bus, fresh_store):
    """A BUY fill on STREAM_EXECUTIONS must land in the in-memory buffer
    even when the DB is unavailable, so REST hydration still surfaces it."""
    await agent.process(
        "executions",
        "rid-1",
        {
            "type": "order_filled",
            "side": "buy",
            "symbol": "BTC/USD",
            "qty": 0.5,
            "fill_price": 100.0,
        },
    )

    # Buffered for hydration
    assert len(fresh_store.notifications) == 1
    record = fresh_store.notifications[0]
    assert "BTC/USD" in record["message"]
    assert record["severity"] == "INFO"
    assert record["notification_type"] == "execution.buy"

    # Also published to the live stream for WS clients
    notifications_calls = [
        c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"
    ]
    assert len(notifications_calls) == 1


@pytest.mark.asyncio
async def test_sell_fill_distinct_from_buy_in_memory(agent, fresh_store):
    """Buy and sell of the same symbol must produce two distinct buffer entries."""
    base = {"type": "order_filled", "symbol": "BTC/USD", "qty": 0.5, "fill_price": 100.0}
    await agent.process("executions", "rid-buy", {**base, "side": "buy"})
    await agent.process("executions", "rid-sell", {**base, "side": "sell"})

    assert len(fresh_store.notifications) == 2
    types = {n["notification_type"] for n in fresh_store.notifications}
    assert types == {"execution.buy", "execution.sell"}


@pytest.mark.asyncio
async def test_other_agent_direct_publish_lands_in_memory(agent, fresh_store):
    """When GradeAgent / ICUpdater publish directly to STREAM_NOTIFICATIONS,
    NotificationAgent observes the stream and records the entry to the
    in-memory buffer (without republishing) so hydration sees it."""
    await agent.process(
        "notifications",
        "rid-grade",
        {
            "msg_id": "grade-evt-1",
            "source": "grade_agent",
            "severity": "CRITICAL",
            "notification_type": "agent_grade",
            "message": "Agent grade F (12%) — accuracy=22%",
            "timestamp": "2026-04-30T12:00:00+00:00",
        },
    )
    assert len(fresh_store.notifications) == 1
    assert fresh_store.notifications[0]["severity"] == "CRITICAL"
    assert fresh_store.notifications[0]["notification_type"] == "agent_grade"


@pytest.mark.asyncio
async def test_self_emit_on_notifications_stream_skipped(agent, fresh_store):
    """NotificationAgent's own re-emits (source == notification_agent) MUST NOT
    be re-recorded — that would double-count every buy/sell fill."""
    await agent.process(
        "notifications",
        "rid-self",
        {
            "msg_id": "self-1",
            "source": "notification_agent",
            "severity": "INFO",
            "message": "BUY FILLED — BTC/USD",
        },
    )
    assert fresh_store.notifications == []


@pytest.mark.asyncio
async def test_invalid_side_does_not_pollute_buffer(agent, fresh_store, mock_bus):
    """Execution events without buy/sell are dropped from publish AND the buffer."""
    await agent.process(
        "executions",
        "rid-x",
        {"type": "order_filled", "side": "hold", "symbol": "BTC/USD"},
    )
    assert fresh_store.notifications == []
    notifications_calls = [
        c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"
    ]
    assert notifications_calls == []


# ---------------------------------------------------------------------------
# REST surface — /dashboard/state, /dashboard/notifications, /clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_state_returns_notifications_in_memory_mode(
    monkeypatch, fresh_store
):
    """The dashboard state endpoint must surface the in-memory buffer when
    the DB is unavailable."""
    fresh_store.record_notification(
        {"msg_id": "n-1", "message": "BUY FILLED — BTC/USD", "severity": "INFO"}
    )

    # Force the in-memory branch and skip Redis enrichment
    async def _no_redis():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(dashboard_v2, "get_redis", _no_redis)

    payload = await dashboard_v2.get_dashboard_state()
    assert payload["mode"] == "in_memory_fallback"
    assert payload["notifications"]
    assert payload["notifications"][0]["message"] == "BUY FILLED — BTC/USD"


@pytest.mark.asyncio
async def test_list_notifications_endpoint_returns_buffer(fresh_store):
    fresh_store.record_notification({"msg_id": "n-1", "message": "first"})
    fresh_store.record_notification({"msg_id": "n-2", "message": "second"})
    payload = await dashboard_v2.list_notifications()
    assert payload["count"] == 2
    assert [n["message"] for n in payload["notifications"]] == ["first", "second"]


@pytest.mark.asyncio
async def test_list_notifications_respects_limit(fresh_store):
    for i in range(10):
        fresh_store.record_notification({"msg_id": f"n-{i}", "message": f"m-{i}"})
    payload = await dashboard_v2.list_notifications(limit=3)
    assert payload["count"] == 3
    # Endpoint returns the most recent entries (tail of the buffer)
    assert [n["message"] for n in payload["notifications"]] == ["m-7", "m-8", "m-9"]


@pytest.mark.asyncio
async def test_clear_notifications_endpoint_empties_buffer(fresh_store):
    fresh_store.record_notification({"msg_id": "n-1", "message": "x"})
    fresh_store.record_notification({"msg_id": "n-2", "message": "y"})
    payload = await dashboard_v2.clear_notifications()
    assert payload["cleared"] == 2
    assert get_runtime_store().notifications == []
