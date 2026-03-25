"""Redis stream event bus primitives for Valkey 8.1.4 / Redis 6-7 compatibility."""

from __future__ import annotations

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


def _serialize(value: Any) -> str:
    """Serialize Python value to Redis-compatible string.
    
    Redis 6-7 compatible: only strings, bytes, ints, floats allowed in XADD.
    Handles: dict -> JSON, list -> JSON, bool -> "true"/"false",
    other -> str()
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _deserialize(value: str) -> Any:
    """Deserialize Redis string to Python value.
    
    Handles: "true"/"false" -> bool, JSON strings -> Python objects,
    other -> str
    """
    if not isinstance(value, str):
        return value
    
    # Handle booleans
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    
    # Try JSON deserialization (for dicts and lists)
    if value.startswith(("{", "[", "\"")):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
    
    return value


def _decode_bytes(value: Any) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


class EventBus:
    """Redis Streams event bus for Valkey 8.1.4 / Redis 6-7 compatibility.
    
    Uses only Redis 6-7 era APIs:
    - XADD, XREADGROUP, XACK
    - XINFO STREAM, XINFO GROUPS (only 'pending' field)
    - XGROUP CREATE with mkstream
    - XAUTOCLAIM (Redis 6.2+)
    """
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def publish(self, stream: str, event: dict[str, Any], maxlen: int = None) -> str | None:
        """Publish event to Redis stream.
        
        All values serialized to strings for Redis 6-7 XADD compatibility.
        """
        try:
            # Serialize all values to strings
            serialized_event = {k: _serialize(v) for k, v in event.items()}
            
            kwargs = {}
            if maxlen:
                kwargs["maxlen"] = maxlen
                kwargs["approximate"] = True
                
            message_id = await self.redis.xadd(stream, serialized_event, **kwargs)
            return str(message_id)
            
        except (ConnectionError, TimeoutError):
            log_structured(
                "warning", "Redis connection error during publish", stream=stream, exc_info=True
            )
            return None
        except Exception:
            log_structured("warning", "Redis publish failed", stream=stream, exc_info=True)
            return None

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 500,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Consume messages from Redis stream using XREADGROUP.
        
        Returns list of (message_id, message_data) tuples.
        """
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
                    # Decode message ID
                    decoded_id = _decode_bytes(msg_id)
                    
                    # Decode and deserialize all fields
                    decoded_fields = {}
                    for k, v in fields.items():
                        key = _decode_bytes(k)
                        value_str = _decode_bytes(v)
                        decoded_fields[key] = _deserialize(value_str)
                    
                    result.append((decoded_id, decoded_fields))
                    
            return result
            
        except (ConnectionError, TimeoutError):
            log_structured(
                "warning", "Redis connection error during consume", stream=stream, exc_info=True
            )
            return []
        except Exception:
            log_structured("warning", "Redis consume failed", stream=stream, exc_info=True)
            return []

    async def acknowledge(self, stream: str, group: str, *ids: str) -> int:
        """Acknowledge messages as processed using XACK."""
        if not ids:
            return 0
        try:
            return int(await self.redis.xack(stream, group, *ids))
        except (ConnectionError, TimeoutError):
            log_structured(
                "warning", "Redis connection error during acknowledge", stream=stream, exc_info=True
            )
            return 0
        except Exception:
            log_structured("warning", "Redis acknowledge failed", stream=stream, exc_info=True)
            return 0

    async def create_stream(self, stream: str) -> None:
        """Create a stream if it doesn't exist using mkstream."""
        try:
            # Use xgroup_create with mkstream which creates stream if missing
            await self.redis.xgroup_create(stream, "temp_init_group", id="0", mkstream=True)
            # Clean up the temp group
            await self.redis.xgroup_destroy(stream, "temp_init_group")
        except ResponseError:
            # Stream already exists, that's fine
            pass
        except Exception:
            pass

    async def create_consumer_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist using mkstream."""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def create_groups(self) -> None:
        """Create all predefined streams and consumer groups."""
        for stream in STREAMS:
            try:
                await self.redis.xgroup_create(
                    stream, DEFAULT_GROUP, id="0", mkstream=True
                )
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def get_stream_info(self) -> dict[str, dict[str, int]]:
        """Get stream statistics using XINFO GROUPS (Redis 6-7 compatible).
        
        Uses only 'pending' field (Redis 6-7 compatible), not 'lag' (Redis 7+).
        """
        info: dict[str, dict[str, int]] = {}
        for stream in STREAMS:
            try:
                length = int(await self.redis.xlen(stream))
                
                try:
                    groups = await self.redis.xinfo_groups(stream)
                except ResponseError:
                    groups = []
                    
                # Calculate lag from 'pending' field only (Redis 6-7 compatible)
                # Note: 'lag' field is Redis 7+, we use 'pending' for compatibility
                lag = 0
                for g in groups:
                    pending = g.get("pending") or g.get(b"pending") or 0
                    lag = max(lag, int(pending))
                    
                info[stream] = {
                    "length": length,
                    "lag": lag,
                    "groups": len(groups),
                }
            except Exception:
                # If stream doesn't exist or other error
                info[stream] = {"length": 0, "lag": 0, "groups": 0}
                
        return info

    async def reclaim_stale(
        self, stream: str, group: str, consumer: str, min_idle_ms: int = 60000
    ) -> list[tuple[str, dict[str, Any]]]:
        """Reclaim stale messages using XAUTOCLAIM (Redis 6.2+).
        
        XAUTOCLAIM is available in Redis 6.2+ and Valkey 8.1.4.
        
        Args:
            stream: Redis stream name
            group: Consumer group name
            consumer: Name of consumer to claim messages for (required)
            min_idle_ms: Minimum idle time in milliseconds (default: 60000 = 60s)
            
        Returns:
            List of (message_id, message_data) tuples for claimed messages
        """
        try:
            result = await self.redis.xautoclaim(
                stream, group, consumer, min_idle_ms, start_id="0-0"
            )
            return self._decode_autoclaim(result)
            
        except (ConnectionError, TimeoutError):
            log_structured(
                "warning", "Redis connection error during reclaim_stale",
                stream=stream, group=group, exc_info=True
            )
            return []
        except ResponseError:
            log_structured(
                "warning", "Redis response error during reclaim_stale",
                stream=stream, group=group, exc_info=True
            )
            return []
        except Exception:
            log_structured(
                "error", "Unexpected error during reclaim_stale",
                stream=stream, group=group, exc_info=True
            )
            return []

    def _decode_autoclaim(self, reclaimed: Any) -> list[tuple[str, dict[str, Any]]]:
        """Decode XAUTOCLAIM result to list of (id, data) tuples.
        
        Handles both tuple format (Redis 7+) and list format (Redis 6.2).
        """
        if not reclaimed:
            return []
            
        if isinstance(reclaimed, tuple):
            # Newer Redis versions return (next_id, messages, deleted_messages)
            _, messages = reclaimed[:2]
        else:
            # Older versions may return list format
            messages = reclaimed[1] if len(reclaimed) > 1 else []
            
        return self._decode_entries(messages)

    def _decode_entries(self, entries: Any) -> list[tuple[str, dict[str, Any]]]:
        """Decode raw Redis entries to Python objects.
        
        Handles all fields in the message with proper deserialization.
        Compatible with Redis 6-7 XREADGROUP and XAUTOCLAIM output formats.
        """
        decoded: list[tuple[str, dict[str, Any]]] = []
        
        if not entries:
            return decoded
            
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
                
            msg_id = str(entry[0])
            fields_data = entry[1]
            
            # Handle different field formats from Redis
            if isinstance(fields_data, dict):
                fields_dict = fields_data
            elif isinstance(fields_data, (list, tuple)) and len(fields_data) % 2 == 0:
                # Convert [k1, v1, k2, v2, ...] to dict (Redis 6 format)
                fields_dict = {}
                for i in range(0, len(fields_data), 2):
                    fields_dict[fields_data[i]] = fields_data[i + 1]
            else:
                fields_dict = {}
            
            # Decode and deserialize all fields
            decoded_fields = {}
            for k, v in fields_dict.items():
                key = _decode_bytes(k)
                value_str = _decode_bytes(v)
                decoded_fields[key] = _deserialize(value_str)
            
            decoded.append((msg_id, decoded_fields))
            
        return decoded


async def create_redis_groups(redis_client: Redis) -> None:
    """Create all Redis streams and consumer groups."""
    await EventBus(redis_client).create_groups()
