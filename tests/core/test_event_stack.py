from __future__ import annotations

import json
from unittest.mock import ANY

import pytest
from redis.exceptions import ResponseError

from api.events.bus import DEFAULT_GROUP, STREAMS, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager


class FakeRedis:
    def __init__(self):
        self.streams = {stream: [] for stream in STREAMS}
        self.hashes = {}
        self.values = {}
        self.acks = []
        self.groups_created = []
        self.autoclaim_messages = []
        self.group_info = {}
        self.busy_streams = set()

    async def xadd(self, stream, payload):
        entry_id = f"{len(self.streams.setdefault(stream, [])) + 1}-0"
        self.streams[stream].append((entry_id, payload))
        return entry_id

    async def xreadgroup(self, groupname, consumername, streams, count=10, block=500):
        stream = next(iter(streams.keys()))
        entries = []
        for entry_id, payload in self.streams.get(stream, [])[:count]:
            entries.append((entry_id, payload))
        self.streams[stream] = self.streams.get(stream, [])[count:]
        return [(stream, entries)]

    async def xack(self, stream, group, *ids):
        self.acks.append((stream, group, ids))
        return len(ids)

    async def xgroup_create(self, stream, group, id_param="0", mkstream=True):
        if stream in self.busy_streams:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups_created.append((stream, group, id_param, mkstream))
        self.streams.setdefault(stream, [])
        return True

    async def xlen(self, stream):
        return len(self.streams.get(stream, []))

    async def xinfo_groups(self, stream):
        if stream not in self.group_info:
            raise ResponseError("NOGROUP")
        return self.group_info[stream]

    async def xautoclaim(self, stream, group, consumer, min_idle_ms, start_id="0-0"):
        return ("0-0", self.autoclaim_messages, [])

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
        return 1

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)
        return 1

    async def delete(self, key):
        self.values.pop(key, None)
        return 1

    async def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key, ttl):
        return True

    async def get(self, key):
        return self.values.get(key)


class DummyConsumer(BaseStreamConsumer):
    def __init__(self, bus, dlq, should_fail=False):
        super().__init__(
            bus, dlq, stream="signals", group=DEFAULT_GROUP, consumer="dummy"
        )
        self.should_fail = should_fail
        self.processed = []

    async def process(self, data):
        if self.should_fail:
            raise RuntimeError("boom")
        self.processed.append(data)


@pytest.mark.asyncio
async def test_event_bus_publish_consume_and_reclaim_decodes_payloads():
    redis = FakeRedis()
    bus = EventBus(redis)

    msg_id = await bus.publish("signals", {"foo": "bar"})
    assert msg_id == "1-0"

    messages = await bus.consume("signals", DEFAULT_GROUP, "worker-1")
    # Should include schema_version and timestamp now
    expected_payload = {"foo": "bar", "schema_version": "v3", "timestamp": ANY}
    actual_payload = messages[0][1]
    # Remove timestamp for comparison since it's dynamic
    actual_payload_copy = actual_payload.copy()
    actual_payload_copy.pop("timestamp", None)
    expected_payload_copy = expected_payload.copy()
    expected_payload_copy.pop("timestamp", None)
    assert actual_payload_copy == expected_payload_copy

    redis.autoclaim_messages = [
        (
            b"2-0",
            {b"payload": json.dumps({"reclaimed": True}).encode("utf-8")},
        )
    ]
    reclaimed = await bus.reclaim_stale("signals", DEFAULT_GROUP, "worker-1")
    # New behavior: all fields are deserialized, including 'payload'
    assert reclaimed == [("b'2-0'", {"payload": {"reclaimed": True}})]


@pytest.mark.asyncio
async def test_event_bus_create_groups_ignores_busygroup_and_reports_stream_info():
    redis = FakeRedis()
    redis.busy_streams = {"signals"}
    redis.group_info = {
        "orders": [{"lag": 4, "pending": 2}],  # Uses 'pending' for Redis 6-7 compat
        "signals": [{"lag": 1, "pending": 0}],
    }
    await redis.xadd("orders", {"payload": json.dumps({"a": 1})})
    bus = EventBus(redis)

    await bus.create_groups()
    info = await bus.get_stream_info()

    assert any(stream == "orders" for stream, *_ in redis.groups_created)
    # Redis 6-7 compatibility: uses 'pending' field, not 'lag' field
    assert info["orders"] == {"lag": 2, "length": 1, "groups": 1}
    assert info["signals"]["lag"] == 0


@pytest.mark.asyncio
async def test_dlq_manager_replays_and_clears_records():
    redis = FakeRedis()
    bus = EventBus(redis)
    dlq = DLQManager(redis, bus)

    await dlq.push("signals", "1-0", {"hello": "world"}, error="boom", retries=3)
    items = await dlq.get_all()
    assert items[0]["stream"] == "signals"

    replayed = await dlq.replay("1-0")
    assert replayed is True
    assert redis.hashes.get("dlq:signals", {}) == {}
    assert redis.streams["signals"][0][1]["hello"] == "world"


@pytest.mark.asyncio
async def test_base_stream_consumer_acks_success_and_dlqs_after_retries():
    redis = FakeRedis()
    bus = EventBus(redis)
    dlq = DLQManager(redis, bus)

    ok_consumer = DummyConsumer(bus, dlq, should_fail=False)
    await ok_consumer._handle_message(
        "1-0", {"msg_id": "test-123", "ok": True, "schema_version": "v3"}
    )
    assert ok_consumer.processed == [
        {"msg_id": "test-123", "ok": True, "schema_version": "v3"}
    ]
    assert redis.acks[-1] == ("signals", DEFAULT_GROUP, ("1-0",))

    failing = DummyConsumer(bus, dlq, should_fail=True)
    await failing._handle_message(
        "2-0", {"msg_id": "test-456", "bad": 1, "schema_version": "v3"}
    )
    await failing._handle_message(
        "2-0", {"msg_id": "test-456", "bad": 1, "schema_version": "v3"}
    )
    await failing._handle_message(
        "2-0", {"msg_id": "test-456", "bad": 1, "schema_version": "v3"}
    )

    dlq_entry = json.loads(redis.hashes["dlq:signals"]["2-0"])
    assert dlq_entry["error"] == "boom"
    assert dlq_entry["retries"] == 3
    assert redis.acks[-1] == ("signals", DEFAULT_GROUP, ("2-0",))
