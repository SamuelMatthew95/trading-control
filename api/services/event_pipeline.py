"""Single Redis -> processing -> WebSocket pipeline with DLQ integration."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

from api.events.bus import DEFAULT_GROUP, STREAMS, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry


class EventPipeline:
    """Owns the only runtime event path: Redis Streams -> transform -> WebSocket."""

    def __init__(
        self,
        bus: EventBus,
        broadcaster: Any,
        dlq: DLQManager,
        *,
        consumer_name: str = "pipeline",
        max_retries: int = 3,
        agent_state: AgentStateRegistry | None = None,
    ):
        self.bus = bus
        self.broadcaster = broadcaster
        self.dlq = dlq
        self.consumer_name = consumer_name
        self.max_retries = max_retries
        self.agent_state = agent_state
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=200)
        self._recent_failures: deque[dict[str, Any]] = deque(maxlen=200)
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="event-pipeline")
        log_structured(
            "info",
            "pipeline_started",
            event_name="pipeline_started",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "consumer": self.consumer_name,
            "stream_count": len(STREAMS),
            "max_retries": self.max_retries,
            "last_error": self._last_error,
            "recent": list(self._recent_events),
            "recent_failures": list(self._recent_failures),
        }

    async def _run(self) -> None:
        while self._running:
            for stream in STREAMS:
                if not self._running:
                    break
                messages = await self.bus.consume(
                    stream,
                    group=DEFAULT_GROUP,
                    consumer=self.consumer_name,
                    count=50,
                    block_ms=250,
                )
                for redis_id, event in messages:
                    await self._process_with_retry(stream, redis_id, event)
            await asyncio.sleep(0.05)

    async def _process_with_retry(self, stream: str, redis_id: str, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or stream)
        msg_id = str(event.get("msg_id") or redis_id)
        ts = str(event.get("timestamp") or datetime.now(timezone.utc).isoformat())
        retry_count = int(event.get("retry_count") or 0)

        try:
            await self._process_message(stream, redis_id, event, event_type, msg_id, ts)
            return
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            self._last_error = error
            failure = {
                "msg_id": msg_id,
                "event_type": event_type,
                "timestamp": ts,
                "error": error,
                "retry_count": retry_count,
                "stream": stream,
            }
            self._recent_failures.appendleft(failure)
            log_structured(
                "error",
                "pipeline_event_failed",
                event_name="pipeline_event_failed",
                msg_id=msg_id,
                event_type=event_type,
                timestamp=ts,
                error=error,
                retry_count=retry_count,
                stream=stream,
            )

            if retry_count + 1 < self.max_retries:
                retried = dict(event)
                retried["retry_count"] = retry_count + 1
                await self.bus.publish(stream, retried)
                await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                log_structured(
                    "warning",
                    "pipeline_event_retried",
                    event_name="pipeline_event_retried",
                    msg_id=msg_id,
                    event_type=event_type,
                    timestamp=ts,
                    error=error,
                    retry_count=retry_count + 1,
                    stream=stream,
                )
                return

            await self.dlq.push(
                stream=stream,
                event_id=msg_id,
                payload=event,
                error=error,
                retries=retry_count + 1,
            )
            await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
            await self.broadcaster.broadcast(
                {
                    "type": "dlq_event",
                    "msg_id": msg_id,
                    "error": error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": event,
                }
            )
            log_structured(
                "error",
                "pipeline_event_sent_to_dlq",
                event_name="pipeline_event_sent_to_dlq",
                msg_id=msg_id,
                event_type=event_type,
                timestamp=ts,
                error=error,
                retry_count=retry_count + 1,
                stream=stream,
            )

    async def _process_message(
        self,
        stream: str,
        redis_id: str,
        event: dict[str, Any],
        event_type: str,
        msg_id: str,
        ts: str,
    ) -> None:
        log_structured(
            "info",
            "pipeline_event_received",
            event_name="pipeline_event_received",
            msg_id=msg_id,
            event_type=event_type,
            timestamp=ts,
            stream=stream,
            redis_id=redis_id,
        )

        outbound = {
            "type": "event",
            "msg_id": msg_id,
            "event_type": event_type,
            "payload": event,
            "timestamp": ts,
        }
        if self.agent_state:
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
            agent_name = payload.get("agent_name") or payload.get("agent")
            if agent_name:
                agent_status = self.agent_state.update(
                    str(agent_name),
                    status=str(payload.get("status") or "running"),
                    health=str(payload.get("health") or "ok"),
                    last_task=str(payload.get("last_task") or event_type),
                )
                await self.broadcaster.broadcast(
                    {
                        "type": "agent_status",
                        "msg_id": msg_id,
                        "event_type": "agent_status",
                        "payload": agent_status,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
        log_structured(
            "info",
            "pipeline_event_processed",
            event_name="pipeline_event_processed",
            msg_id=msg_id,
            event_type=event_type,
            timestamp=ts,
            stream=stream,
        )

        await self.broadcaster.broadcast(outbound)
        log_structured(
            "info",
            "websocket_broadcast",
            event_name="websocket_broadcast",
            msg_id=msg_id,
            event_type=event_type,
            timestamp=ts,
            stream=stream,
        )

        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
        log_structured(
            "info",
            "pipeline_event_acked",
            event_name="pipeline_event_acked",
            msg_id=msg_id,
            event_type=event_type,
            timestamp=ts,
            stream=stream,
        )
        self._recent_events.appendleft(outbound)
