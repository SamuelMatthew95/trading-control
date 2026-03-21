"""Redis stream event bus primitives."""

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


class EventBus:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def publish(self, stream: str, event: dict[str, Any]) -> str:
        payload = {"payload": json.dumps(event, default=str)}
        try:
            message_id = await self.redis.xadd(stream, payload)
            return str(message_id)
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during publish", stream=stream, error=str(exc)
            )
            return None
        except Exception as exc:
            log_structured(
                "warning", "Redis publish failed", stream=stream, error=str(exc)
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
        try:
            messages = await self.redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
            return self._decode_message_batch(messages)
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during consume", stream=stream, error=str(exc)
            )
            return []
        except Exception as exc:
            log_structured(
                "warning", "Redis consume failed", stream=stream, error=str(exc)
            )
            return []

    async def acknowledge(self, stream: str, group: str, *ids: str) -> int:
        if not ids:
            return 0
        try:
            return int(await self.redis.xack(stream, group, *ids))
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning", "Redis connection error during acknowledge", stream=stream, error=str(exc)
            )
            return 0
        except Exception as exc:
            log_structured(
                "warning", "Redis acknowledge failed", stream=stream, error=str(exc)
            )
            return 0

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
        """Reclaim stale messages with robust error handling."""
        try:
            reclaimed = await self.redis.xautoclaim(
                stream, group, DEFAULT_GROUP, min_idle_ms, start_id="0-0"
            )
            return self._decode_autoclaim(reclaimed)
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning",
                "Redis connection error during reclaim_stale",
                stream=stream,
                group=group,
                error=str(exc)
            )
            return []
        except ResponseError as exc:
            log_structured(
                "warning",
                "Redis response error during reclaim_stale",
                stream=stream,
                group=group,
                error=str(exc)
            )
            return []
        except Exception as exc:
            log_structured(
                "error",
                "Unexpected error during reclaim_stale",
                stream=stream,
                group=group,
                error=str(exc)
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


async def create_groups(redis_client: Redis) -> None:
    await EventBus(redis_client).create_groups()
