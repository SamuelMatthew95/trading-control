from __future__ import annotations

import pytest

from api.events.bus import PIPELINE_GROUP
from api.events.dlq import DLQManager
from api.services.event_pipeline import EventPipeline


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
