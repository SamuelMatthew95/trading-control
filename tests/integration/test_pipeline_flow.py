from __future__ import annotations

import pytest

from api.events.bus import PIPELINE_GROUP
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.runtime_state import set_db_available, set_runtime_store
from api.services.event_pipeline import EventPipeline
from api.services.persistence_routing import (
    PersistRoute,
    determine_persist_route,
    should_route_agent_log_to_memory,
)


class _FakeBus:
    def __init__(self):
        self.acked = []

    async def consume(self, stream, group, consumer, count=10, block_ms=500):
        return []

    async def acknowledge(self, stream, group, msg_id):
        self.acked.append((stream, group, msg_id))

    async def publish(self, stream, event):
        return "2-0"


class _FakeRedis:
    async def hset(self, *_args, **_kwargs):
        return 1


class _FakeBroadcaster:
    def __init__(self):
        self.active_connections = 1
        self.sent = []

    async def broadcast(self, payload):
        self.sent.append(payload)


class _FakeWriter:
    def __init__(self):
        self.calls = []

    async def write_order(self, msg_id, stream, data):
        self.calls.append((msg_id, stream, data))
        return True

    async def write_execution(self, *args, **kwargs):
        return True

    async def write_agent_log(self, *args, **kwargs):
        return True

    async def write_system_metric(self, *args, **kwargs):
        return True

    async def write_trade_performance(self, *args, **kwargs):
        return True

    async def write_risk_alert(self, *args, **kwargs):
        return True

    async def write_vector_memory(self, *args, **kwargs):
        return True

    async def write_agent_grade(self, *args, **kwargs):
        return True

    async def write_ic_weight(self, *args, **kwargs):
        return True

    async def write_reflection_output(self, *args, **kwargs):
        return True

    async def write_strategy_proposal(self, *args, **kwargs):
        return True

    async def write_notification(self, *args, **kwargs):
        return True


@pytest.mark.asyncio
async def test_pipeline_processes_and_broadcasts_event():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)

    await pipeline._process_message(
        "market_ticks",
        "1-0",
        {"type": "tick", "msg_id": "m1", "timestamp": "2026-01-01T00:00:00Z"},
        "tick",
        "m1",
        "2026-01-01T00:00:00Z",
    )

    assert len(ws.sent) == 1
    assert ws.sent[0]["msg_id"] == "m1"
    assert ws.sent[0]["type"] == "event"
    assert bus.acked == [("market_ticks", PIPELINE_GROUP, "1-0")]


@pytest.mark.asyncio
async def test_pipeline_persists_orders_before_ack(monkeypatch):
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: True)
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)
    writer = _FakeWriter()
    pipeline.safe_writer = writer

    event = {"type": "order", "msg_id": "o1", "symbol": "AAPL"}
    await pipeline._process_message("orders", "2-0", event, "order", "o1", "2026-01-01T00:00:00Z")

    assert writer.calls == [("o1", "orders", event)]
    assert bus.acked == [("orders", PIPELINE_GROUP, "2-0")]


# ---------------------------------------------------------------------------
# Persistence routing tests
# ---------------------------------------------------------------------------


def test_determine_persist_route_skip_for_unknown_stream():
    route = determine_persist_route("market_ticks", {})
    assert route == PersistRoute.SKIP


def test_determine_persist_route_skip_when_db_unavailable(monkeypatch):
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: False)
    event = {
        "schema_version": "v3",
        "source": "test",
        "trace_id": "abc",
        "level": "INFO",
        "message": "hi",
    }
    route = determine_persist_route("orders", event)
    assert route == PersistRoute.SKIP


def test_determine_persist_route_db_when_available(monkeypatch):
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: True)
    event = {
        "schema_version": "v3",
        "source": "test",
        "trace_id": "abc",
        "level": "INFO",
        "message": "hi",
    }
    route = determine_persist_route("orders", event)
    assert route == PersistRoute.DB


def test_should_route_agent_log_to_memory_missing_message():
    event = {"schema_version": "v3", "source": "s", "trace_id": "t", "level": "INFO"}
    assert should_route_agent_log_to_memory(event) is True


def test_should_route_agent_log_to_memory_missing_level():
    event = {"schema_version": "v3", "source": "s", "trace_id": "t", "message": "hi"}
    assert should_route_agent_log_to_memory(event) is True


def test_should_route_agent_log_to_memory_wrong_schema_version():
    event = {
        "schema_version": "v2",
        "source": "s",
        "trace_id": "t",
        "level": "INFO",
        "message": "hi",
    }
    assert should_route_agent_log_to_memory(event) is True


def test_should_route_agent_log_to_memory_all_fields_present():
    event = {
        "schema_version": "v3",
        "source": "s",
        "trace_id": "t",
        "level": "INFO",
        "message": "hi",
    }
    assert should_route_agent_log_to_memory(event) is False


def test_determine_persist_route_memory_for_malformed_agent_log(monkeypatch):
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: True)
    # Missing "message" field makes this malformed
    event = {"schema_version": "v3", "source": "s", "trace_id": "t", "level": "INFO"}
    route = determine_persist_route("agent_logs", event)
    assert route == PersistRoute.MEMORY


@pytest.mark.asyncio
async def test_pipeline_routes_malformed_agent_log_to_memory(monkeypatch):
    """Malformed agent_log payload lands in InMemoryStore, not DB, not DLQ."""
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)

    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: False)

    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)
    writer = _FakeWriter()
    pipeline.safe_writer = writer

    malformed = {"type": "agent_log", "msg_id": "al1", "source": "test_agent"}
    await pipeline._process_message(
        "agent_logs", "3-0", malformed, "agent_log", "al1", "2026-01-01T00:00:00Z"
    )

    # Writer must NOT have been called — route was MEMORY
    assert all("write_agent_log" not in str(c) for c in writer.calls)
    # Row must be in the in-memory store
    assert len(store.agent_logs) == 1
    assert store.agent_logs[0]["source"] == "test_agent"
    # Event still acked and broadcast
    assert bus.acked == [("agent_logs", PIPELINE_GROUP, "3-0")]
    assert any(m.get("type") == "event" for m in ws.sent)
