from __future__ import annotations

import pytest

from api.constants import FieldName
from api.events.bus import PIPELINE_GROUP
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.runtime_state import set_db_available, set_runtime_store
from api.services.event_pipeline import EventPipeline
from api.services.persistence_routing import (
    PersistRoute,
    determine_persist_route,
    should_route_agent_log_to_memory,
    write_event_to_memory,
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


def test_determine_persist_route_memory_when_db_unavailable(monkeypatch):
    """All handled streams route to MEMORY (not SKIP) when DB is down."""
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: False)
    for stream in ("orders", "agent_logs", "agent_grades", "learning_events", "executions"):
        assert determine_persist_route(stream, {}) == PersistRoute.MEMORY, stream


def test_determine_persist_route_db_when_available(monkeypatch):
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: True)
    route = determine_persist_route("orders", {})
    assert route == PersistRoute.DB


def test_determine_persist_route_skip_for_agent_owned_when_db_available(monkeypatch):
    """Agent-owned streams are persisted by the producing agent directly, so the
    pipeline must SKIP the redundant DB write (it only ever failed validation)
    and just broadcast."""
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: True)
    for stream in ("agent_grades", "factor_ic_history", "reflection_outputs", "proposals"):
        assert determine_persist_route(stream, {}) == PersistRoute.SKIP, stream


def test_determine_persist_route_agent_owned_still_memory_when_db_down(monkeypatch):
    """DB down: agent-owned streams still route to MEMORY so the dashboard keeps
    hydrating (challenger grades, which only flow via the stream, still surface)."""
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: False)
    for stream in ("agent_grades", "factor_ic_history", "reflection_outputs", "proposals"):
        assert determine_persist_route(stream, {}) == PersistRoute.MEMORY, stream


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


def test_should_route_agent_log_to_memory_missing_source():
    event = {"schema_version": "v3", "trace_id": "t", "level": "INFO", "message": "hi"}
    assert should_route_agent_log_to_memory(event) is True


def test_should_route_agent_log_to_memory_missing_trace_id():
    event = {"schema_version": "v3", "source": "s", "level": "INFO", "message": "hi"}
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
    event = {"schema_version": "v3", "source": "s", "trace_id": "t", "level": "INFO"}
    route = determine_persist_route("agent_logs", event)
    assert route == PersistRoute.MEMORY


# ---------------------------------------------------------------------------
# write_event_to_memory dispatch tests
# ---------------------------------------------------------------------------


def test_write_event_to_memory_agent_logs():
    store = InMemoryStore()
    event = {"source": "sig", "message": "hi", "level": "INFO", "trace_id": "t"}
    write_event_to_memory("agent_logs", "m1", event, store)
    assert len(store.agent_logs) == 1
    assert store.agent_logs[0][FieldName.SOURCE] == "sig"


def test_write_event_to_memory_orders():
    store = InMemoryStore()
    event = {"symbol": "BTC/USD", "side": "buy"}
    write_event_to_memory("orders", "m2", event, store)
    assert len(store.orders) == 1
    assert store.orders[0]["symbol"] == "BTC/USD"


def test_write_event_to_memory_agent_grades():
    store = InMemoryStore()
    event = {"score": 0.9, "grade_type": "accuracy"}
    write_event_to_memory("agent_grades", "m3", event, store)
    assert len(store.grade_history) == 1


def test_write_event_to_memory_learning_events():
    store = InMemoryStore()
    event = {"content": "some insight", "content_type": "text"}
    write_event_to_memory("learning_events", "m4", event, store)
    assert len(store.vector_memory) == 1


def test_write_event_to_memory_trade_performance():
    store = InMemoryStore()
    event = {FieldName.ORDER_ID: "ord-1", "pnl": 50.0}
    write_event_to_memory("trade_performance", "m5", event, store)
    assert len(store.trade_feed) == 1


def test_write_event_to_memory_generic_fallback():
    """Streams without a dedicated bucket land in event_history."""
    store = InMemoryStore()
    event = {"detail": "some risk alert"}
    write_event_to_memory("risk_alerts", "m6", event, store)
    assert len(store.event_history) == 1
    assert store.event_history[0]["kind"] == "risk_alerts"


def test_write_event_to_memory_executions_generic_fallback():
    store = InMemoryStore()
    write_event_to_memory("executions", "m7", {"fill_price": 100.0}, store)
    assert len(store.event_history) == 1
    assert store.event_history[0]["kind"] == "executions"


def test_write_event_to_memory_proposals_generic_fallback():
    store = InMemoryStore()
    write_event_to_memory("proposals", "m8", {"proposal_type": "rebalance"}, store)
    assert len(store.event_history) == 1
    assert store.event_history[0]["kind"] == "proposals"


def test_write_event_to_memory_reflection_outputs_generic_fallback():
    store = InMemoryStore()
    write_event_to_memory("reflection_outputs", "m9", {"insights": []}, store)
    assert len(store.event_history) == 1


def test_write_event_to_memory_factor_ic_history_generic_fallback():
    store = InMemoryStore()
    write_event_to_memory("factor_ic_history", "m10", {"factor_name": "momentum"}, store)
    assert len(store.event_history) == 1


def test_write_event_to_memory_notifications_generic_fallback():
    store = InMemoryStore()
    write_event_to_memory("notifications", "m11", {"message": "order filled"}, store)
    assert len(store.event_history) == 1


# ---------------------------------------------------------------------------
# End-to-end pipeline memory-fallback tests
# ---------------------------------------------------------------------------


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
    pipeline.safe_writer = _FakeWriter()

    malformed = {"type": "agent_log", "msg_id": "al1", "source": "test_agent"}
    await pipeline._process_message(
        "agent_logs", "3-0", malformed, "agent_log", "al1", "2026-01-01T00:00:00Z"
    )

    assert len(store.agent_logs) == 1
    assert store.agent_logs[0]["source"] == "test_agent"
    assert bus.acked == [("agent_logs", PIPELINE_GROUP, "3-0")]
    assert any(m.get("type") == "event" for m in ws.sent)


@pytest.mark.asyncio
async def test_pipeline_routes_all_streams_to_memory_when_db_down(monkeypatch):
    """Every handled stream writes to InMemoryStore when DB is unavailable."""
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)
    monkeypatch.setattr("api.services.persistence_routing.is_db_available", lambda: False)

    bus = _FakeBus()
    ws = _FakeBroadcaster()
    pipeline = EventPipeline(bus, ws, DLQManager(_FakeRedis(), bus))
    pipeline.safe_writer = _FakeWriter()

    cases = [
        ("agent_logs", "5-0", {"source": "s", "msg_id": "x"}, "agent_log", "x"),
        ("orders", "6-0", {"symbol": "ETH/USD"}, "order", "y"),
        ("agent_grades", "7-0", {"score": 1.0}, "grade", "z"),
        ("risk_alerts", "8-0", {"detail": "spike"}, "risk_alert", "w"),
    ]
    for stream, redis_id, event, etype, mid in cases:
        await pipeline._process_message(stream, redis_id, event, etype, mid, "2026-01-01T00:00:00Z")

    assert len(store.agent_logs) == 1
    assert len(store.orders) == 1
    assert len(store.grade_history) == 1
    assert len(store.event_history) >= 1  # risk_alerts → generic fallback
    # SafeWriter was never called
    assert pipeline.safe_writer.calls == []
