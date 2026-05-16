"""Base class for agents that consume multiple Redis streams."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import Any

from api.constants import FieldName, LifecyclePhase
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry

_IDLE_HEARTBEAT_INTERVAL = 60  # seconds between "alive but waiting" heartbeats


class MultiStreamAgent:
    """Dispatches Redis stream messages to ``process()`` for each stream in ``streams``.

    Each running instance registers itself in ``agent_instances`` on start and
    marks itself retired on stop, giving full lifecycle traceability even as
    agents are hot-restarted or scaled out.
    """

    _state_name: str = ""  # Override in subclass to enable AgentStateRegistry tracking

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        streams: list[str],
        consumer: str,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        self.bus = bus
        self.dlq = dlq
        self.streams = streams
        self.consumer = consumer
        self.agent_state = agent_state
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._instance_id: str | None = None
        self._events_processed: int = 0

    # ------------------------------------------------------------------
    # Public introspection — used by AgentSupervisor to detect crashes
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Agent identity string (matches the consumer name)."""
        return self.consumer

    @property
    def has_crashed(self) -> bool:
        """True if the task finished with an unhandled exception (not cancelled).

        MultiStreamAgent._run() swallows processing exceptions internally so
        the task rarely dies, but we expose this property so AgentSupervisor
        can iterate all agents uniformly without AttributeError.
        """
        return (
            self._task is not None
            and self._task.done()
            and not self._task.cancelled()
            and self._task.exception() is not None
        )

    # ------------------------------------------------------------------
    # Instance lifecycle registration
    # ------------------------------------------------------------------

    async def _register_instance(self) -> None:
        """Register this agent instance in the DB. Non-fatal on error."""
        try:
            from api.services.agents.db_helpers import (  # noqa: PLC0415
                register_agent_instance,
                write_agent_lifecycle_event,
            )

            pool_name = self._state_name or self.consumer
            self._instance_id = await register_agent_instance(
                instance_key=self.consumer,
                pool_name=pool_name,
            )
            await write_agent_lifecycle_event(
                pool_name=pool_name,
                instance_id=self._instance_id,
                lifecycle_phase=LifecyclePhase.STARTED,
            )
            log_structured(
                "info",
                "agent_instance_registered",
                consumer=self.consumer,
                instance_id=self._instance_id,
            )
        except Exception:
            log_structured("warning", "agent_instance_register_skipped", exc_info=True)

    async def _retire_instance(self) -> None:
        """Mark this instance as retired in the DB. Non-fatal on error."""
        if self._instance_id is None:
            return
        try:
            from api.services.agents.db_helpers import (  # noqa: PLC0415
                retire_agent_instance,
                write_agent_lifecycle_event,
            )

            await retire_agent_instance(self._instance_id)
            await write_agent_lifecycle_event(
                pool_name=self._state_name or self.consumer,
                instance_id=self._instance_id,
                lifecycle_phase=LifecyclePhase.STOPPED,
            )
            log_structured(
                "info",
                "agent_instance_retired",
                consumer=self.consumer,
                instance_id=self._instance_id,
            )
        except Exception:
            log_structured("warning", "agent_instance_retire_skipped", exc_info=True)

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        await self._register_instance()
        self._running = True
        if self.agent_state and self._state_name:
            self.agent_state.transition(
                self._state_name,
                "ready",
                task=f"subscribed:{','.join(self.streams)}",
            )
        for stream in self.streams:
            log_structured(
                "info",
                "agent_stream_subscribed",
                agent=self.consumer,
                stream=stream,
            )
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.consumer}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._retire_instance()

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _write_alive_heartbeat(self, status: str = "idle:waiting") -> None:
        """Write a heartbeat even when no stream events arrive.

        Uses ``_state_name`` as the agent key so the dashboard always shows
        the correct agent name. Silently skips if ``_state_name`` is unset or
        if Redis is unavailable.
        """
        if not self._state_name:
            return
        try:
            from api.redis_client import get_redis as _get_redis  # noqa: PLC0415
            from api.services.agent_heartbeat import (  # noqa: PLC0415
                write_heartbeat as _write_heartbeat,
            )

            redis = await _get_redis()
            await _write_heartbeat(
                redis,
                self._state_name,
                f"agent:{status}",
                event_count=self._events_processed,
            )
        except Exception:
            pass

    async def _run(self) -> None:
        if self.agent_state and self._state_name:
            self.agent_state.transition(self._state_name, "active", task="polling")
        # Write startup heartbeat so the dashboard sees the agent immediately.
        await self._write_alive_heartbeat("idle:starting")
        _last_heartbeat = time.monotonic()
        while self._running:
            now = time.monotonic()
            if now - _last_heartbeat >= _IDLE_HEARTBEAT_INTERVAL:
                await self._write_alive_heartbeat("idle:waiting")
                _last_heartbeat = now
            for stream in self.streams:
                messages = await self.bus.consume(
                    stream,
                    group=DEFAULT_GROUP,
                    consumer=self.consumer,
                    count=20,
                    block_ms=100,
                )
                for redis_id, data in messages:
                    try:
                        if self.agent_state and self._state_name:
                            self.agent_state.transition(
                                self._state_name,
                                "processing",
                                task=f"{stream}:{redis_id}",
                            )
                        log_structured(
                            "info",
                            "multi_stream_event_consumed",
                            agent=self.consumer,
                            stream=stream,
                            redis_id=redis_id,
                        )
                        await self.process(stream, redis_id, data)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                        self._events_processed += 1
                        if self.agent_state and self._state_name:
                            self.agent_state.record_event(
                                self._state_name,
                                task=f"{stream}:{data.get(FieldName.TYPE, 'event')}",
                            )
                            self.agent_state.transition(self._state_name, "active", task="polling")
                        # Best-effort event counter on instance row
                        if self._instance_id:
                            try:
                                from api.services.agents.db_helpers import (  # noqa: PLC0415
                                    increment_instance_event_count,
                                )

                                await increment_instance_event_count(self._instance_id)
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception as exc:  # noqa: BLE001
                        if self._instance_id:
                            try:
                                from api.services.agents.db_helpers import (  # noqa: PLC0415
                                    write_agent_lifecycle_event,
                                )

                                await write_agent_lifecycle_event(
                                    pool_name=self._state_name or self.consumer,
                                    instance_id=self._instance_id,
                                    lifecycle_phase=LifecyclePhase.CRASHED,
                                    details={
                                        FieldName.STREAM: stream,
                                        FieldName.REDIS_ID: redis_id,
                                    },
                                )
                            except Exception:
                                pass
                        log_structured(
                            "error",
                            "pipeline_agent_process_failed",
                            agent=self.consumer,
                            stream=stream,
                            exc_info=True,
                        )
                        # Guard: if DLQ push or ack fails here, the exception would
                        # propagate out of the except block, crash the task, and leave
                        # the message in the PEL forever — MultiStreamAgent has no
                        # reclaim_stale(), so it would never be re-delivered.
                        try:
                            await self.dlq.push(stream, redis_id, data, error=str(exc), retries=1)
                            await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                        except Exception:
                            log_structured(
                                "error",
                                "pipeline_agent_dlq_or_ack_failed",
                                agent=self.consumer,
                                stream=stream,
                                redis_id=redis_id,
                                exc_info=True,
                            )
            await asyncio.sleep(0.05)
