from __future__ import annotations

import pytest

from api.events.bus import PIPELINE_GROUP
from api.events.dlq import DLQManager
from api.services.event_pipeline import EventPipeline
from api.services.persistence_routing import PersistRoute, determine_persist_route


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
        self.agent_log_calls = []

    async def write_order(self, msg_id, stream, data):
        self.calls.append((msg_id, stream, data))
        return True

    async def write_execution(self, *args, **kwargs):
        return True

    async def write_agent_log(self, *args, **kwargs):
        self.agent_log_calls.append((args, kwargs))
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
async def test_pipeline_persists_orders_before_ack():
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


@pytest.mark.asyncio
async def test_pipeline_falls_back_to_memory_on_invalid_agent_log():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)
    writer = _FakeWriter()
    pipeline.safe_writer = writer

    from api.in_memory_store import InMemoryStore
    from api.runtime_state import set_runtime_store

    set_runtime_store(InMemoryStore())

    event = {"type": "agent_log", "msg_id": "l1", "source": "reasoning", "message": "thinking"}
    await pipeline._process_message(
        "agent_logs",
        "3-0",
        event,
        "agent_log",
        "l1",
        "2026-01-01T00:00:00Z",
    )

    from api.runtime_state import get_runtime_store

    logs = get_runtime_store().agent_logs
    assert len(logs) == 1
    assert logs[0]["id"] == "mem-l1"
    assert logs[0]["message"] == "thinking"
    assert logs[0]["persist_path"] == "memory"
    assert logs[0]["db_persist_status"] == "skipped_missing_required_fields"
    assert writer.calls == []
    assert bus.acked == [("agent_logs", PIPELINE_GROUP, "3-0")]


@pytest.mark.asyncio
async def test_pipeline_writes_valid_agent_log_to_db_writer():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)
    writer = _FakeWriter()
    pipeline.safe_writer = writer

    event = {
        "type": "agent_log",
        "msg_id": "l2",
        "source": "reasoning",
        "message": "thinking",
        "level": "info",
    }
    await pipeline._process_message(
        "agent_logs",
        "4-0",
        event,
        "agent_log",
        "l2",
        "2026-01-01T00:00:00Z",
    )

    assert len(writer.agent_log_calls) == 1
    assert bus.acked == [("agent_logs", PIPELINE_GROUP, "4-0")]


@pytest.mark.asyncio
async def test_pipeline_falls_back_when_payload_dict_missing_message():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)
    writer = _FakeWriter()
    pipeline.safe_writer = writer

    from api.in_memory_store import InMemoryStore
    from api.runtime_state import set_runtime_store

    set_runtime_store(InMemoryStore())

    event = {
        "type": "agent_log",
        "msg_id": "l3",
        "payload": {"source": "reasoning", "level": "info"},
    }
    await pipeline._process_message(
        "agent_logs",
        "5-0",
        event,
        "agent_log",
        "l3",
        "2026-01-01T00:00:00Z",
    )

    from api.runtime_state import get_runtime_store

    logs = get_runtime_store().agent_logs
    assert logs[-1]["id"] == "mem-l3"
    assert logs[-1]["persist_path"] == "memory"
    assert writer.agent_log_calls == []
    assert bus.acked == [("agent_logs", PIPELINE_GROUP, "5-0")]


@pytest.mark.asyncio
async def test_invalid_agent_log_keeps_pipeline_flow_and_persists_memory_row():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)
    writer = _FakeWriter()
    pipeline.safe_writer = writer

    from api.in_memory_store import InMemoryStore
    from api.runtime_state import set_runtime_store

    set_runtime_store(InMemoryStore())

    event = {
        "type": "agent_log",
        "msg_id": "l4",
        "payload": {
            "source": "reasoning",
            "trace_id": "trace-1",
            "level": "warning",
            "event": "deliberation",
        },
        "timestamp": "2026-01-01T00:00:00Z",
    }

    await pipeline._process_message(
        "agent_logs",
        "6-0",
        event,
        "agent_log",
        "l4",
        "2026-01-01T00:00:00Z",
    )

    from api.runtime_state import get_runtime_store

    logs = get_runtime_store().agent_logs
    assert logs[-1]["id"] == "mem-l4"
    assert logs[-1]["agent_name"] == "reasoning"
    assert logs[-1]["trace_id"] == "trace-1"
    assert logs[-1]["message"] == "deliberation"
    assert logs[-1]["log_level"] == "warning"
    assert logs[-1]["persist_path"] == "memory"
    assert logs[-1]["db_persist_status"] == "skipped_missing_required_fields"

    assert writer.agent_log_calls == []
    assert bus.acked == [("agent_logs", PIPELINE_GROUP, "6-0")]
    assert len(ws.sent) == 1
    assert ws.sent[0]["msg_id"] == "l4"


@pytest.mark.asyncio
async def test_determine_persist_route_matrix_is_consistent():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    dlq = DLQManager(_FakeRedis(), bus)
    pipeline = EventPipeline(bus, ws, dlq)

    assert (
        determine_persist_route(
            stream="unknown_stream",
            event={"type": "x"},
            writer=None,
        )
        is PersistRoute.SKIP
    )

    assert (
        determine_persist_route(
            stream="orders",
            event={"type": "order", "msg_id": "o1"},
            writer=pipeline.safe_writer.write_order,
        )
        is PersistRoute.DB
    )

    assert (
        determine_persist_route(
            stream="agent_logs",
            event={"type": "agent_log", "msg_id": "l7", "message": "no-level"},
            writer=pipeline.safe_writer.write_agent_log,
        )
        is PersistRoute.MEMORY
    )
