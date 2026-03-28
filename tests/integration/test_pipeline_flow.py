from __future__ import annotations

import pytest

from api.services.event_pipeline import EventPipeline


class _FakeBus:
    def __init__(self):
        self._messages = [("1-0", {"type": "tick", "msg_id": "m1", "timestamp": "2026-01-01T00:00:00Z"})]
        self.acked = []

    async def consume(self, stream, group, consumer, count=10, block_ms=500):
        if stream != "market_ticks" or not self._messages:
            return []
        out = list(self._messages)
        self._messages = []
        return out

    async def acknowledge(self, stream, group, msg_id):
        self.acked.append((stream, group, msg_id))


class _FakeBroadcaster:
    def __init__(self):
        self.active_connections = 1
        self.sent = []

    async def broadcast(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_pipeline_processes_and_broadcasts_event():
    bus = _FakeBus()
    ws = _FakeBroadcaster()
    pipeline = EventPipeline(bus, ws)

    await pipeline._process_message("market_ticks", "1-0", {"type": "tick", "msg_id": "m1", "timestamp": "2026-01-01T00:00:00Z"})

    assert len(ws.sent) == 1
    assert ws.sent[0]["msg_id"] == "m1"
    assert bus.acked == [("market_ticks", "workers", "1-0")]
