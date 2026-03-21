"""Base consumer with at-least-once stream semantics."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured


class BaseStreamConsumer(ABC):
    def __init__(
        self, bus: EventBus, dlq: DLQManager, stream: str, group: str, consumer: str
    ):
        self.bus = bus
        self.dlq = dlq
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"consumer:{self.stream}")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    @abstractmethod
    async def process(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
        try:
            reclaimed = await self.bus.reclaim_stale(self.stream, self.group)
        except Exception as exc:
            log_structured("warning", "Redis reclaim failed, skipping", error=str(exc))
            reclaimed = []
        for msg_id, data in reclaimed:
            await self._handle_message(msg_id, data)
        while self._running:
            messages = await self.bus.consume(
                self.stream, self.group, self.consumer, count=10, block_ms=500
            )
            for msg_id, data in messages:
                await self._handle_message(msg_id, data)

    async def _handle_message(self, msg_id: str, data: dict[str, Any]) -> None:
        try:
            await self.process(data)
            await self.bus.acknowledge(self.stream, self.group, msg_id)
        except Exception as exc:  # noqa: BLE001
            send_to_dlq = await self.dlq.should_dlq(msg_id)
            if send_to_dlq:
                retries_key = f"dlq:retries:{msg_id}"
                retries = int(await self.dlq.redis.get(retries_key) or 0)
                await self.dlq.push(
                    self.stream, msg_id, data, error=str(exc), retries=retries
                )
                await self.bus.acknowledge(self.stream, self.group, msg_id)
            log_structured(
                "warning",
                "Stream consumer failed to process message",
                stream=self.stream,
                message_id=msg_id,
                error=str(exc),
                dlq=send_to_dlq,
            )
