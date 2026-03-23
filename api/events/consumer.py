"""Base consumer with at-least-once stream semantics."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any

from redis.exceptions import ConnectionError, TimeoutError

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured


class BaseStreamConsumer(ABC):
    def __init__(self, bus: EventBus, dlq: DLQManager, stream: str, group: str, consumer: str):
        self.bus = bus
        self.dlq = dlq
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run(), name=f"consumer:{self.stream}")

    async def stop(self) -> None:
        self._running = False
        self._shutdown_event.set()

        if self._task is None:
            return

        # Give the task a chance to finish gracefully
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            log_structured("warning", "Consumer task timeout, cancelling", stream=self.stream)
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        except Exception as exc:
            log_structured(
                "error", "Unexpected error stopping consumer", stream=self.stream, exc_info=True
            )
        finally:
            self._task = None

    @abstractmethod
    async def process(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
        try:
            reclaimed = await self._safe_reclaim_stale()
        except Exception as exc:
            log_structured("warning", "Redis reclaim failed, skipping", exc_info=True)
            reclaimed = []

        for msg_id, data in reclaimed:
            if not self._running:
                break
            await self._handle_message(msg_id, data)

        while self._running:
            try:
                messages = await self.bus.consume(
                    self.stream, self.group, self.consumer, count=10, block_ms=500
                )
                for msg_id, data in messages:
                    if not self._running:
                        break
                    await self._handle_message(msg_id, data)
            except (ConnectionError, TimeoutError) as exc:
                log_structured(
                    "warning",
                    "Redis connection error in consumer loop",
                    stream=self.stream,
                    exc_info=True,
                )
                # Brief backoff before retry
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                break
            except Exception as exc:
                log_structured(
                    "error", "Unexpected error in consumer loop", stream=self.stream, exc_info=True
                )
                break

    async def _safe_reclaim_stale(self) -> list[tuple[str, dict[str, Any]]]:
        """Safely reclaim stale messages with timeout and error handling."""
        try:
            return await asyncio.wait_for(
                self.bus.reclaim_stale(self.stream, self.group), timeout=3.0
            )
        except asyncio.TimeoutError:
            log_structured("warning", "Reclaim stale timeout during shutdown", stream=self.stream)
            return []
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "warning",
                "Redis connection error during reclaim",
                stream=self.stream,
                exc_info=True,
            )
            return []

    async def _handle_message(self, msg_id: str, data: dict[str, Any]) -> None:
        try:
            await self.process(data)
            await self.bus.acknowledge(self.stream, self.group, msg_id)
        except Exception as exc:  # noqa: BLE001
            try:
                send_to_dlq = await self.dlq.should_dlq(msg_id)
                if send_to_dlq:
                    retries_key = f"dlq:retries:{msg_id}"
                    retries = int(await self.dlq.redis.get(retries_key) or 0)
                    await self.dlq.push(self.stream, msg_id, data, exc_info=True, retries=retries)
                    await self.bus.acknowledge(self.stream, self.group, msg_id)
            except (ConnectionError, TimeoutError) as redis_exc:
                log_structured(
                    "error",
                    "Redis error during DLQ handling",
                    stream=self.stream,
                    message_id=msg_id,
                    exc_info=True,
                )
            log_structured(
                "warning",
                "Stream consumer failed to process message",
                stream=self.stream,
                message_id=msg_id,
                exc_info=True,
                dlq=send_to_dlq if "send_to_dlq" in locals() else "unknown",
            )
