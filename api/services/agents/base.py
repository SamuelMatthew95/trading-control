"""Base class for agents that consume multiple Redis streams."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from api.constants import FieldName
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry


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
            from api.services.agents.db_helpers import (
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
                lifecycle_phase="started",
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
            from api.services.agents.db_helpers import (
                retire_agent_instance,
                write_agent_lifecycle_event,
            )

            await retire_agent_instance(self._instance_id)
            await write_agent_lifecycle_event(
                pool_name=self._state_name or self.consumer,
                instance_id=self._instance_id,
                lifecycle_phase="stopped",
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

    async def _run(self) -> None:
        if self.agent_state and self._state_name:
            self.agent_state.transition(self._state_name, "active", task="polling")
        while self._running:
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
                        if self.agent_state and self._state_name:
                            self.agent_state.record_event(
                                self._state_name,
                                task=f"{stream}:{data.get(FieldName.TYPE, 'event')}",
                            )
                            self.agent_state.transition(self._state_name, "active", task="polling")
                        # Best-effort event counter on instance row
                        if self._instance_id:
                            try:
                                from api.services.agents.db_helpers import (
                                    increment_instance_event_count,
                                )

                                await increment_instance_event_count(self._instance_id)
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception as exc:  # noqa: BLE001
                        if self._instance_id:
                            try:
                                from api.services.agents.db_helpers import (
                                    write_agent_lifecycle_event,
                                )

                                await write_agent_lifecycle_event(
                                    pool_name=self._state_name or self.consumer,
                                    instance_id=self._instance_id,
                                    lifecycle_phase="crashed",
                                    details={"stream": stream, "redis_id": redis_id},
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
