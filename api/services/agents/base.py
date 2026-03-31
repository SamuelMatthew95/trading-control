"""Base class for agents that consume multiple Redis streams."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry


class MultiStreamAgent:
    """Dispatches Redis stream messages to ``process()`` for each stream in ``streams``."""

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

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.consumer}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
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
                        await self.process(stream, redis_id, data)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                        if self.agent_state and self._state_name:
                            self.agent_state.record_event(
                                self._state_name, task=f"{stream}:{data.get('type', 'event')}"
                            )
                    except Exception as exc:  # noqa: BLE001
                        log_structured(
                            "error",
                            "pipeline_agent_process_failed",
                            agent=self.consumer,
                            stream=stream,
                            exc_info=True,
                        )
                        await self.dlq.push(stream, redis_id, data, error=str(exc), retries=1)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
            await asyncio.sleep(0.05)
