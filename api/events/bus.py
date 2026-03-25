"""Redis stream event bus primitives."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from api.observability import log_structured

STREAMS = (
    "market_ticks",
    "signals",
    "orders",
    "executions",
    "risk_alerts",
    "learning_events",
    "system_metrics",
    "agent_logs",
)
DEFAULT_GROUP = "workers"


class EventBus:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def publish(self, stream: str, event: dict[str, Any], maxlen: int = None) -> str:
        """Publish event to Redis stream with proper serialization."""
        import json
        try:
            # Serialize all dict/list values to JSON strings
            serialized_event = {}
            for k, v in event.items():
                if isinstance(v, (dict, list)):
                    serialized_event[k] = json.dumps(v)
                elif isinstance(v, bool):
                    serialized_event[k] = str(v)
                else:
                    serialized_event[k] = v
            
            kwargs = {}
            if maxlen:
                kwargs["maxlen"] = maxlen
                kwargs["approximate"] = True
            message_id = await self.redis.xadd(stream, serialized_event, **kwargs)
            return str(message_id)
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during publish", stream=stream, exc_info=True
            )
            return None
        except Exception as exc:
            log_structured(
                "warning", "Redis publish failed", stream=stream, exc_info=True
            )
            return None

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 500,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Consume messages with JSON deserialization."""
        import json
        try:
            messages = await self.redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
            result = []
            for stream_name, stream_messages in messages:
                for msg_id, fields in stream_messages:
                    # Convert bytes to strings and deserialize JSON
                    decoded_fields = {}
                    for k, v in fields.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        value = v.decode() if isinstance(v, bytes) else v
                        # Try to deserialize JSON
                        try:
                            if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                                decoded_fields[key] = json.loads(value)
                            elif value == 'True':
                                decoded_fields[key] = True
                            elif value == 'False':
                                decoded_fields[key] = False
                            else:
                                decoded_fields[key] = value
                        except json.JSONDecodeError:
                            decoded_fields[key] = value
                    result.append((msg_id.decode() if isinstance(msg_id, bytes) else msg_id, decoded_fields))
            return result
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during consume", stream=stream, exc_info=True
            )
            return []
        except Exception as exc:
            log_structured(
                "warning", "Redis consume failed", stream=stream, exc_info=True
            )
            return []

    async def acknowledge(self, stream: str, group: str, *ids: str) -> int:
        if not ids:
            return 0
        try:
            return int(await self.redis.xack(stream, group, *ids))
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during acknowledge", stream=stream, exc_info=True
            )
            return 0
        except Exception as exc:
            log_structured(
                "warning", "Redis acknowledge failed", stream=stream, exc_info=True
            )
            return 0

    async def create_stream(self, stream: str) -> None:
        """Create a stream if it doesn't exist."""
        try:
            await self.redis.xadd(stream, {"_init": "1"}, maxlen=1)
            # Remove the init message
            messages = await self.redis.xrange(stream)
            if messages:
                await self.redis.xdel(stream, messages[0][0])
        except Exception as e:
            # Stream might already exist
            pass

    async def create_consumer_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def create_groups(self) -> None:
        for stream in STREAMS:
            try:
                await self.redis.xgroup_create(
                    stream, DEFAULT_GROUP, id="0", mkstream=True
                )
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def get_stream_info(self) -> dict[str, dict[str, int]]:
        info: dict[str, dict[str, int]] = {}
        for stream in STREAMS:
            length = int(await self.redis.xlen(stream))
            try:
                groups = await self.redis.xinfo_groups(stream)
            except ResponseError:
                groups = []
            lag = 0
            for g in groups:
                lag = max(
                    lag,
                    int(
                        g.get("lag")
                        or g.get("pending")
                        or g.get(b"lag")
                        or g.get(b"pending")
                        or 0
                    ),
                )
            info[stream] = {"lag": lag, "length": length, "groups": len(groups)}
        return info

    async def reclaim_stale(
        self, stream: str, group: str, min_idle_ms: int = 60000
    ) -> list[tuple[str, dict[str, Any]]]:
        try:
            result = self.redis.xautoclaim(
                stream, group, DEFAULT_GROUP, min_idle_ms, start_id="0-0"
            )
            # Handle both sync and async Redis clients
            if asyncio.iscoroutine(result):
                reclaimed = await result
            else:
                reclaimed = result
            return self._decode_autoclaim(reclaimed)
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during reclaim_stale", stream=stream, group=group, exc_info=True
            )
            return []
        except ResponseError as exc:
            log_structured(
                "warning", "Redis response error during reclaim_stale", stream=stream, group=group, exc_info=True
            )
            return []
        except Exception as exc:
            log_structured(
                "error", "Unexpected error during reclaim_stale", stream=stream, group=group, exc_info=True
            )
            return []

    def _decode_autoclaim(self, reclaimed: Any) -> list[tuple[str, dict[str, Any]]]:
        if isinstance(reclaimed, tuple):
            _, messages, *_ = reclaimed
        else:
            messages = reclaimed[1] if reclaimed else []
        return self._decode_entries(messages)

    def _decode_message_batch(self, messages: Any) -> list[tuple[str, dict[str, Any]]]:
        decoded: list[tuple[str, dict[str, Any]]] = []
        for _, entries in messages:
            decoded.extend(self._decode_entries(entries))
        return decoded

    def _decode_entries(self, entries: Any) -> list[tuple[str, dict[str, Any]]]:
        decoded: list[tuple[str, dict[str, Any]]] = []
        for msg_id, fields in entries:
            payload_raw = fields.get("payload") or fields.get(b"payload") or "{}"
            if isinstance(payload_raw, bytes):
                payload_raw = payload_raw.decode("utf-8")
            decoded.append((str(msg_id), json.loads(payload_raw)))
        return decoded


async def create_redis_groups(redis_client: Redis) -> None:
    """Create all Redis streams and consumer groups."""
    await EventBus(redis_client).create_groups()


def main() -> None:
    """CLI entry point for manual Redis group creation."""
    import asyncio
    from api.redis_client import get_redis
    
    async def _init():
        try:
            redis_client = await get_redis()
            await create_redis_groups(redis_client)
            print("✅ Redis streams and groups initialized successfully")
        except Exception as exc:
            print(f"❌ Failed to initialize Redis streams and groups: {exc}")
            raise
    
    asyncio.run(_init())
