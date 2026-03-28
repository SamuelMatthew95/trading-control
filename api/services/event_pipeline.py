"""Single Redis -> processing -> WebSocket pipeline."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from api.events.bus import DEFAULT_GROUP, STREAMS, EventBus
from api.observability import log_structured


class EventPipeline:
    """Owns the only runtime event path: Redis Streams -> transform -> WebSocket."""

    def __init__(self, bus: EventBus, broadcaster: Any, *, consumer_name: str = "pipeline"):
        self.bus = bus
        self.broadcaster = broadcaster
        self.consumer_name = consumer_name
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=200)
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="event-pipeline")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "consumer": self.consumer_name,
            "stream_count": len(STREAMS),
            "last_error": self._last_error,
            "recent": list(self._recent_events),
        }

    async def _run(self) -> None:
        while self._running:
            for stream in STREAMS:
                if not self._running:
                    break
                try:
                    messages = await self.bus.consume(
                        stream,
                        group=DEFAULT_GROUP,
                        consumer=self.consumer_name,
                        count=50,
                        block_ms=250,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._last_error = str(exc)
                    log_structured(
                        "error",
                        "pipeline_redis_consume_failed",
                        event_type="redis_error",
                        msg_id="none",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        stream=stream,
                        error=str(exc),
                    )
                    continue

                for redis_id, event in messages:
                    await self._process_message(stream, redis_id, event)
            await asyncio.sleep(0.05)

    async def _process_message(self, stream: str, redis_id: str, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or stream)
        msg_id = str(event.get("msg_id") or redis_id)
        ts = str(event.get("timestamp") or datetime.now(timezone.utc).isoformat())

        log_structured(
            "info",
            "pipeline_redis_event_received",
            event_type=event_type,
            msg_id=msg_id,
            timestamp=ts,
            stream=stream,
            redis_id=redis_id,
        )

        transformed = {
            "event_type": event_type,
            "msg_id": msg_id,
            "timestamp": ts,
            "stream": stream,
            "payload": event,
        }
        log_structured(
            "info",
            "pipeline_event_processed",
            event_type=event_type,
            msg_id=msg_id,
            timestamp=ts,
            stream=stream,
        )

        try:
            await self.broadcaster.broadcast(transformed)
            await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
            self._recent_events.appendleft(transformed)
            log_structured(
                "info",
                "pipeline_ws_published",
                event_type=event_type,
                msg_id=msg_id,
                timestamp=ts,
                stream=stream,
                websocket_clients=self.broadcaster.active_connections,
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            log_structured(
                "error",
                "pipeline_publish_failed",
                event_type=event_type,
                msg_id=msg_id,
                timestamp=ts,
                stream=stream,
                error=str(exc),
            )
