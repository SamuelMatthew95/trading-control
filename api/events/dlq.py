"""Dead-letter queue management for Redis streams."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from api.events.bus import STREAMS, EventBus


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
            "retries": retries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.hset(f"dlq:{stream}", event_id, json.dumps(record, default=str))

    async def should_dlq(self, event_id: str) -> bool:
        retries_key = f"dlq:retries:{event_id}"
        retries = int(await self.redis.incr(retries_key))
        await self.redis.expire(retries_key, 86400)
        return retries >= 3

    async def get_all(self) -> list[dict[str, Any]]:
        return await self.get_recent(limit=10000)

    async def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for stream in STREAMS:
            values = await self.redis.hgetall(f"dlq:{stream}")
            for value in values.values():
                raw = value.decode("utf-8") if isinstance(value, bytes) else value
                items.append(json.loads(raw))
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:limit]

    async def stats(self) -> dict[str, Any]:
        per_stream: dict[str, int] = {}
        retry_buckets: dict[str, int] = {}
        total = 0
        last_error: str | None = None

        for stream in STREAMS:
            values = await self.redis.hgetall(f"dlq:{stream}")
            count = len(values)
            per_stream[stream] = count
            total += count
            for value in values.values():
                raw = value.decode("utf-8") if isinstance(value, bytes) else value
                event = json.loads(raw)
                retries = int(event.get("retries", 0))
                retry_buckets[str(retries)] = retry_buckets.get(str(retries), 0) + 1
                last_error = event.get("error") or last_error

        return {
            "total": total,
            "per_stream": per_stream,
            "retry_buckets": retry_buckets,
            "last_error": last_error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def replay(self, event_id: str) -> bool:
        for stream in STREAMS:
            raw = await self.redis.hget(f"dlq:{stream}", event_id)
            if raw is None:
                continue
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            record = json.loads(raw)
            await self.bus.publish(record["stream"], record["payload"])
            await self.clear(event_id)
            return True
        return False

    async def clear(self, event_id: str) -> None:
        for stream in STREAMS:
            await self.redis.hdel(f"dlq:{stream}", event_id)
        await self.redis.delete(f"dlq:retries:{event_id}")
