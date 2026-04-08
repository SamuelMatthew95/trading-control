"""Redis stream event bus primitives for Valkey 8.1.4 / Redis 6-7 compatibility."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from api.constants import (
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_GITHUB_PRS,
    STREAM_GRADED_DECISIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_MARKET_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_NOTIFICATIONS,
    STREAM_ORDERS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
    STREAM_TRADE_LIFECYCLE,
    STREAM_TRADE_PERFORMANCE,
)
from api.observability import log_structured
from api.schema_version import DB_SCHEMA_VERSION

STREAMS = (
    STREAM_MARKET_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_SIGNALS,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
    STREAM_ORDERS,
    STREAM_EXECUTIONS,
    STREAM_TRADE_PERFORMANCE,
    STREAM_RISK_ALERTS,
    STREAM_LEARNING_EVENTS,
    STREAM_SYSTEM_METRICS,
    STREAM_AGENT_LOGS,
    STREAM_AGENT_GRADES,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_PROPOSALS,
    STREAM_NOTIFICATIONS,
    STREAM_GITHUB_PRS,
    STREAM_TRADE_LIFECYCLE,
)
DEFAULT_GROUP = "workers"
# Separate group for the broadcast pipeline so it reads independently
# of the agent workers — prevents the pipeline from stealing agent messages.
PIPELINE_GROUP = "broadcast_pipeline"


def _serialize(value: Any) -> str:
    """Strict Redis-safe serialization (Valkey 8 safe).

    Redis Streams (XADD) ONLY accepts: str, bytes, int, float
    NOT dict, NOT list, NOT None

    Handles:
    - None -> ""
    - str/int/float -> str(value)
    - dict/list/bool/anything else -> JSON
    """
    if value is None:
        return ""

    if isinstance(value, (str, int, float)):
        return str(value)

    # EVERYTHING else -> JSON (dicts, lists, booleans, objects)
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        # Fallback: force to string
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
    if value.startswith(("{", "[", '"')):
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

    async def publish(self, stream: str, event: dict[str, Any], maxlen: int | None = None) -> str:
        """Publish event to Redis stream with schema version."""
        # Bug fix: always include schema_version so consumer never sends to DLQ
        event.setdefault("schema_version", DB_SCHEMA_VERSION)
        event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        # Serialize all values to strings with defensive fallback
        serialized_event = {}
        for k, v in event.items():
            try:
                serialized_event[k] = _serialize(v)
            except Exception:
                # NEVER allow raw values through
                serialized_event[k] = str(v)

        # EXTRA SAFETY: catch any unserialized dicts (bugs early)
        for k, v in serialized_event.items():
            if isinstance(v, dict):
                error_msg = f"UNSERIALIZED FIELD: {k}={v}"
                log_structured("error", error_msg, stream=stream, event_keys=list(event.keys()))
                raise ValueError(error_msg)

        try:
            kwargs = {}
            if maxlen:
                kwargs["maxlen"] = maxlen
                kwargs["approximate"] = True

            message_id = await self.redis.xadd(stream, serialized_event, **kwargs)

            # Log successful publish
            log_structured(
                "info",
                "event_published",
                stream=stream,
                message_id=str(message_id),
                keys=list(serialized_event.keys()),
            )

            return str(message_id)

        except (RedisConnectionError, RedisTimeoutError):
            log_structured(
                "warning",
                "Redis connection error during publish",
                stream=stream,
                exc_info=True,
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
            for _stream_name, stream_messages in messages:
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

            # Log successful consumption
            if result:
                log_structured(
                    "info",
                    "event_consumed",
                    stream=stream,
                    group=group,
                    consumer=consumer,
                    count=len(result),
                )

            return result

        except (RedisConnectionError, RedisTimeoutError):
            log_structured(
                "warning",
                "Redis connection error during consume",
                stream=stream,
                exc_info=True,
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
        except (RedisConnectionError, RedisTimeoutError):
            log_structured(
                "warning",
                "Redis connection error during acknowledge",
                stream=stream,
                exc_info=True,
            )
            return 0
        except Exception:
            log_structured("warning", "Redis acknowledge failed", stream=stream, exc_info=True)
            return 0

    async def create_stream(self, stream: str) -> None:
        """Create a stream if it doesn't exist using mkstream."""
        try:
            # Use xgroup_create with mkstream which creates stream if missing
            await self.redis.xgroup_create(stream, "temp_init_group", "0", mkstream=True)
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
            await self.redis.xgroup_create(stream, group, "0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def create_groups(self) -> None:
        """Create all predefined streams and consumer groups."""
        for stream in STREAMS:
            for group in (DEFAULT_GROUP, PIPELINE_GROUP):
                try:
                    await self.redis.xgroup_create(stream, group, "$", mkstream=True)
                except ResponseError as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
                    if group == DEFAULT_GROUP:
                        # Check if the agents group needs fast-forwarding
                        await self._maybe_fastforward_group(stream)

    async def _maybe_fastforward_group(self, stream: str) -> None:
        """If group's last-delivered-id is far behind, fast-forward to prevent replay."""
        try:
            groups = await self.redis.xinfo_groups(stream)
            stream_info = await self.redis.xinfo_stream(stream)
            last_entry = stream_info.get("last-generated-id") or stream_info.get(
                b"last-generated-id"
            )
            if not last_entry:
                return

            for group in groups:
                name = group.get("name") or group.get(b"name")
                if isinstance(name, bytes):
                    name = name.decode()
                if name != DEFAULT_GROUP:
                    continue

                pending = int(group.get("pending") or group.get(b"pending") or 0)
                last_delivered = group.get("last-delivered-id") or group.get(b"last-delivered-id")
                if isinstance(last_delivered, bytes):
                    last_delivered = last_delivered.decode()

                # If there are no pending messages and we're at the beginning, fast-forward
                if pending == 0 and last_delivered in ("0", "0-0", "0-1"):
                    await self.redis.xgroup_setid(stream, DEFAULT_GROUP, "$")
                    log_structured(
                        "info",
                        "consumer_group_fastforwarded",
                        stream=stream,
                        group=DEFAULT_GROUP,
                    )
        except Exception:
            log_structured("warning", "fastforward_check_failed", stream=stream, exc_info=True)

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
            decoded = self._decode_autoclaim(result)

            # Log successful reclaim
            if decoded:
                log_structured(
                    "info",
                    "events_reclaimed",
                    stream=stream,
                    group=group,
                    consumer=consumer,
                    count=len(decoded),
                )

            return decoded

        except (RedisConnectionError, RedisTimeoutError):
            log_structured(
                "warning",
                "Redis connection error during reclaim_stale",
                stream=stream,
                group=group,
                exc_info=True,
            )
            return []
        except ResponseError:
            log_structured(
                "warning",
                "Redis response error during reclaim_stale",
                stream=stream,
                group=group,
                exc_info=True,
            )
            return []
        except Exception:
            log_structured(
                "error",
                "Unexpected error during reclaim_stale",
                stream=stream,
                group=group,
                exc_info=True,
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
