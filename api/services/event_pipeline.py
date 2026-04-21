"""Single Redis -> processing -> WebSocket pipeline with DLQ integration."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

from api.constants import (
    DLQ_MAX_RETRIES,
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_LEARNING_EVENTS,
    STREAM_NOTIFICATIONS,
    STREAM_ORDERS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
)
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionFactory
from api.events.bus import PIPELINE_GROUP, STREAMS, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
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
        max_retries: int = DLQ_MAX_RETRIES,
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
        self.safe_writer = SafeWriter(AsyncSessionFactory)
        # Pipeline uses its own consumer group so it never competes with agent workers.
        self._group = PIPELINE_GROUP

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
                    group=self._group,
                    consumer=self.consumer_name,
                    count=50,
                    block_ms=250,
                )
                for redis_id, event in messages:
                    await self._process_with_retry(stream, redis_id, event)
            await asyncio.sleep(0.05)  # Event processing throttle - allowed

    async def _process_with_retry(self, stream: str, redis_id: str, event: dict[str, Any]) -> None:
        event_type = str(event.get(FieldName.TYPE) or stream)
        msg_id = str(event.get(FieldName.MSG_ID) or redis_id)
        ts = str(event.get(FieldName.TIMESTAMP) or datetime.now(timezone.utc).isoformat())
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
                await self.bus.acknowledge(stream, self._group, redis_id)
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
            await self.bus.acknowledge(stream, self._group, redis_id)
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

        # Persist is best-effort — failures must never block broadcasting or acking.
        # Agents already write directly to the DB; the pipeline persist is a
        # secondary safety net.  Strict validation errors (wrong schema, missing
        # fields) are logged as warnings, not propagated.
        try:
            await self._persist_event(stream=stream, msg_id=msg_id, event=event)
        except Exception:  # noqa: BLE001
            log_structured(
                "warning",
                "pipeline_persist_skipped",
                stream=stream,
                msg_id=msg_id,
                exc_info=True,
            )

        outbound = {
            "type": "event",
            "stream": stream,
            "msg_id": msg_id,
            "event_type": event_type,
            "payload": event,
            "timestamp": ts,
        }
        if not is_db_available():
            get_runtime_store().add_event(
                {
                    "id": msg_id,
                    "kind": event_type,
                    "source": str(event.get(FieldName.SOURCE) or stream),
                    "created_at": ts,
                }
            )
        if self.agent_state:
            payload = (
                event.get(FieldName.PAYLOAD)
                if isinstance(event.get(FieldName.PAYLOAD), dict)
                else event
            )
            agent_name = payload.get(FieldName.AGENT_NAME) or payload.get(FieldName.AGENT)
            if agent_name:
                agent_status = self.agent_state.update(
                    str(agent_name),
                    status=str(payload.get(FieldName.STATUS) or "running"),
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

        await self.bus.acknowledge(stream, self._group, redis_id)
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

    async def _persist_event(self, stream: str, msg_id: str, event: dict[str, Any]) -> None:
        # NOTE: system_metrics is intentionally omitted — write_system_metric has a
        # different positional signature that is incompatible with (msg_id, stream, data).
        # Agents write system_metrics directly; the pipeline just broadcasts them.
        writer_methods = {
            STREAM_ORDERS: self.safe_writer.write_order,
            STREAM_EXECUTIONS: self.safe_writer.write_execution,
            STREAM_AGENT_LOGS: self.safe_writer.write_agent_log,
            STREAM_TRADE_PERFORMANCE: self.safe_writer.write_trade_performance,
            STREAM_RISK_ALERTS: self.safe_writer.write_risk_alert,
            STREAM_LEARNING_EVENTS: self.safe_writer.write_vector_memory,
            STREAM_AGENT_GRADES: self.safe_writer.write_agent_grade,
            STREAM_FACTOR_IC_HISTORY: self.safe_writer.write_ic_weight,
            STREAM_REFLECTION_OUTPUTS: self.safe_writer.write_reflection_output,
            STREAM_PROPOSALS: self.safe_writer.write_strategy_proposal,
            STREAM_NOTIFICATIONS: self.safe_writer.write_notification,
        }
        writer = writer_methods.get(stream)
        if writer is None:
            return
        ok = await writer(msg_id=msg_id, stream=stream, data=event)
        if not ok:
            log_structured(
                "warning",
                "pipeline_persist_returned_false",
                stream=stream,
                msg_id=msg_id,
            )
