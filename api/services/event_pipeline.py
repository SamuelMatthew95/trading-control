"""Single Redis -> processing -> WebSocket pipeline with DLQ integration."""

from __future__ import annotations

import asyncio
from collections import deque
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
from api.services.persistence_routing import (
    PersistRoute,
    determine_persist_route,
    write_event_to_memory,
)
from api.utils import now_iso


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
        self._processed_msg_ids: deque[str] = deque(maxlen=5000)
        self._processed_msg_id_set: set[str] = set()
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
            timestamp=now_iso(),
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
            FieldName.RUNNING: self._running,
            FieldName.CONSUMER: self.consumer_name,
            FieldName.STREAM_COUNT: len(STREAMS),
            FieldName.MAX_RETRIES: self.max_retries,
            FieldName.LAST_ERROR: self._last_error,
            FieldName.RECENT: list(self._recent_events),
            FieldName.RECENT_FAILURES: list(self._recent_failures),
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
        ts = str(event.get(FieldName.TIMESTAMP) or now_iso())
        retry_count = int(event.get(FieldName.RETRY_COUNT) or 0)

        try:
            await self._process_message(stream, redis_id, event, event_type, msg_id, ts)
            return
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            self._last_error = error
            failure = {
                FieldName.MSG_ID: msg_id,
                FieldName.EVENT_TYPE: event_type,
                FieldName.TIMESTAMP: ts,
                FieldName.ERROR: error,
                FieldName.RETRY_COUNT: retry_count,
                FieldName.STREAM: stream,
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
                retried[FieldName.RETRY_COUNT] = retry_count + 1
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
                    FieldName.TYPE: "dlq_event",
                    FieldName.MSG_ID: msg_id,
                    FieldName.ERROR: error,
                    FieldName.TIMESTAMP: now_iso(),
                    FieldName.PAYLOAD: event,
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
        if msg_id in self._processed_msg_id_set:
            await self.bus.acknowledge(stream, self._group, redis_id)
            log_structured(
                "info",
                "pipeline_event_deduplicated",
                event_name="pipeline_event_deduplicated",
                msg_id=msg_id,
                event_type=event_type,
                timestamp=ts,
                stream=stream,
            )
            return

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
        wrote_event_history = False
        try:
            wrote_event_history = await self._persist_event(
                stream=stream, msg_id=msg_id, event=event
            )
        except Exception:  # noqa: BLE001
            log_structured(
                "warning",
                "pipeline_persist_skipped",
                stream=stream,
                msg_id=msg_id,
                exc_info=True,
            )

        outbound = {
            FieldName.TYPE: "event",
            FieldName.STREAM: stream,
            FieldName.MSG_ID: msg_id,
            FieldName.EVENT_TYPE: event_type,
            FieldName.PAYLOAD: event,
            FieldName.TIMESTAMP: ts,
        }
        # Skip the generic events-feed append when the memory persist above
        # already landed this msg_id in event_history (fall-through streams) —
        # otherwise the same event shows up twice in the dashboard feed.
        if not is_db_available() and not wrote_event_history:
            get_runtime_store().add_event(
                {
                    FieldName.ID: msg_id,
                    FieldName.KIND: event_type,
                    FieldName.SOURCE: str(event.get(FieldName.SOURCE) or stream),
                    FieldName.CREATED_AT: ts,
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
                    health=str(payload.get(FieldName.HEALTH) or "ok"),
                    last_task=str(payload.get(FieldName.LAST_TASK) or event_type),
                )
                await self.broadcaster.broadcast(
                    {
                        FieldName.TYPE: "agent_status",
                        FieldName.MSG_ID: msg_id,
                        FieldName.EVENT_TYPE: "agent_status",
                        FieldName.PAYLOAD: agent_status,
                        FieldName.TIMESTAMP: now_iso(),
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

        await self.bus.acknowledge(stream, self._group, redis_id)
        self._remember_processed_msg_id(msg_id)
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

    def _remember_processed_msg_id(self, msg_id: str) -> None:
        if msg_id in self._processed_msg_id_set:
            return
        if len(self._processed_msg_ids) == self._processed_msg_ids.maxlen:
            stale = self._processed_msg_ids.popleft()
            self._processed_msg_id_set.discard(stale)
        self._processed_msg_ids.append(msg_id)
        self._processed_msg_id_set.add(msg_id)

    async def _persist_event(self, stream: str, msg_id: str, event: dict[str, Any]) -> bool:
        """Persist one event; returns True when it landed in event_history."""
        # Route is selected before any write attempt — no exception-driven fallbacks.
        route = determine_persist_route(stream, event)

        if route == PersistRoute.SKIP:
            return False

        if route == PersistRoute.MEMORY:
            wrote_event_history = write_event_to_memory(stream, msg_id, event, get_runtime_store())
            log_structured(
                "info",
                "pipeline_event_routed_to_memory",
                stream=stream,
                msg_id=msg_id,
            )
            return wrote_event_history

        # DB route — system_metrics is intentionally omitted (different signature).
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
            return False
        ok = await writer(msg_id=msg_id, stream=stream, data=event)
        if not ok:
            log_structured(
                "warning",
                "pipeline_persist_returned_false",
                stream=stream,
                msg_id=msg_id,
            )
        return False
