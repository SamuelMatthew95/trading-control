"""Dead-letter queue management for Redis streams."""

from __future__ import annotations

import json
from typing import Any

from api.constants import (
    DLQ_MAX_RETRIES,
    DLQ_RETRIES_TTL_SECONDS,
    REDIS_KEY_DLQ,
    REDIS_KEY_DLQ_RETRIES,
    FieldName,
)
from api.events.bus import STREAMS, EventBus
from api.utils import bytes_to_text, now_iso


class DLQManager:
    def __init__(self, redis_client, bus: EventBus):
        self.redis = redis_client
        self.bus = bus

    async def push(
        self,
        stream: str,
        event_id: str,
        payload: dict[str, Any],
        error: str,
        retries: int,
    ) -> None:
        record = {
            "stream": stream,
            "event_id": event_id,
            "payload": payload,
            "error": error,
            FieldName.RETRIES: retries,
            "timestamp": now_iso(),
        }
        await self.redis.hset(
            REDIS_KEY_DLQ.format(stream=stream), event_id, json.dumps(record, default=str)
        )

    async def should_dlq(self, event_id: str) -> bool:
        retries_key = REDIS_KEY_DLQ_RETRIES.format(event_id=event_id)
        retries = int(await self.redis.incr(retries_key))
        await self.redis.expire(retries_key, DLQ_RETRIES_TTL_SECONDS)
        return retries >= DLQ_MAX_RETRIES

    async def get_all(self) -> list[dict[str, Any]]:
        return await self.get_recent(limit=10000)

    async def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for stream in STREAMS:
            values = await self.redis.hgetall(REDIS_KEY_DLQ.format(stream=stream))
            for value in values.values():
                items.append(json.loads(bytes_to_text(value)))
        items.sort(key=lambda x: x.get(FieldName.TIMESTAMP, ""), reverse=True)
        return items[:limit]

    async def stats(self) -> dict[str, Any]:
        per_stream: dict[str, int] = {}
        retry_buckets: dict[str, int] = {}
        total = 0
        last_error: str | None = None

        for stream in STREAMS:
            values = await self.redis.hgetall(REDIS_KEY_DLQ.format(stream=stream))
            count = len(values)
            per_stream[stream] = count
            total += count
            for value in values.values():
                event = json.loads(bytes_to_text(value))
                retries = int(event.get(FieldName.RETRIES, 0))
                retry_buckets[str(retries)] = retry_buckets.get(str(retries), 0) + 1
                last_error = event.get(FieldName.ERROR) or last_error

        return {
            FieldName.TOTAL: total,
            FieldName.PER_STREAM: per_stream,
            FieldName.RETRY_BUCKETS: retry_buckets,
            FieldName.LAST_ERROR: last_error,
            "timestamp": now_iso(),
        }

    async def replay(self, event_id: str) -> bool:
        for stream in STREAMS:
            raw = await self.redis.hget(REDIS_KEY_DLQ.format(stream=stream), event_id)
            if raw is None:
                continue
            record = json.loads(bytes_to_text(raw))
            await self.bus.publish(record[FieldName.STREAM], record[FieldName.PAYLOAD])
            await self.clear(event_id)
            return True
        return False

    async def clear(self, event_id: str) -> None:
        for stream in STREAMS:
            await self.redis.hdel(REDIS_KEY_DLQ.format(stream=stream), event_id)
        await self.redis.delete(REDIS_KEY_DLQ_RETRIES.format(event_id=event_id))
