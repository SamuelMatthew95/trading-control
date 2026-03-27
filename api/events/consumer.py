"""Base consumer with at-least-once stream semantics and robust shutdown."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any

from redis.exceptions import ConnectionError, TimeoutError

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured

ACCEPTED_SCHEMA_VERSIONS = {"v3", "legacy", None, ""}


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
        self._backoff = 1  # Exponential backoff state
        self._max_backoff = 10  # Maximum backoff in seconds

    async def start(self) -> None:
        """Start the consumer with robust error handling."""
        if self._task and not self._task.done():
            log_structured("warning", "Consumer already running", stream=self.stream)
            return
        
        self._running = True
        self._shutdown_event.clear()
        self._backoff = 1  # Reset backoff
        
        self._task = asyncio.create_task(self._run(), name=f"consumer:{self.stream}")
        log_structured("info", "Consumer started", stream=self.stream, consumer=self.consumer)

    async def stop(self) -> None:
        """Stop the consumer with immediate shutdown and task cleanup."""
        self._running = False
        self._shutdown_event.set()
        
        if self._task is None:
            return
        
        # Wait for task completion with shorter timeout
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except asyncio.TimeoutError:
            log_structured("warning", "Consumer task timeout, cancelling", stream=self.stream)
            # Cancel the task
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        except asyncio.CancelledError:
            # Expected when task is cancelled
            pass
        except Exception:
            log_structured("warning", "Redis connection error during consume", stream=self.stream)
        finally:
            self._task = None
            log_structured("info", "Consumer stopped", stream=self.stream)

    @abstractmethod
    async def process(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def extract_msg_id(self, data: dict[str, Any]) -> str:
        """Extract and validate msg_id from event data. Centralized enforcement."""
        msg_id = data.get("msg_id")
        if not msg_id:
            log_structured(
                "error",
                "Missing msg_id in producer payload",
                extra={
                    "stream": self.stream,
                    "data_keys": list(data.keys()),
                },
            )
            raise RuntimeError(f"Missing msg_id in {self.stream}")
        return msg_id

    async def _run_once(self) -> None:
        """Run a single iteration of the consumer loop for testing."""
        try:
            # Claim pending messages (PEL recovery)
            reclaimed = await self._safe_reclaim_stale()
            for msg_id, data in reclaimed:
                if not self._running:
                    break
                await self._handle_message(msg_id, data)
        except Exception as exc:
            log_structured("warning", "Redis reclaim failed, skipping", exc_info=True)

        # Try to consume new messages with non-blocking call
        try:
            messages = await self.bus.consume(
                self.stream, self.group, self.consumer, count=10, block_ms=0  # Non-blocking
            )
            for msg_id, data in messages:
                if not self._running:
                    break
                await self._handle_message(msg_id, data)
        except Exception:
            log_structured("warning", "Consumer iteration failed", stream=self.stream)

    async def _run(self) -> None:
        """Main consumer loop with responsive shutdown and non-blocking operations."""
        log_structured("info", "Consumer loop starting", stream=self.stream)
        
        try:
            # Initial reclaim of stale messages
            reclaimed = await self._safe_reclaim_stale()
        except Exception as exc:
            log_structured("warning", "Initial reclaim failed, skipping", exc_info=True)
            reclaimed = []

        # Process reclaimed messages
        for msg_id, data in reclaimed:
            if not self._running:
                break
            await self._handle_message(msg_id, data)

        # Main loop with responsive shutdown
        while self._running and not self._shutdown_event.is_set():
            try:
                # Use shorter blocking time for responsive shutdown
                messages = await self.bus.consume(
                    self.stream, self.group, self.consumer, count=10, block_ms=100
                )
                
                # Reset backoff on successful consume
                self._backoff = 1
                
                # Process messages
                for msg_id, data in messages:
                    if not self._running or self._shutdown_event.is_set():
                        break
                    await self._handle_message(msg_id, data)
                    
            except (ConnectionError, TimeoutError) as exc:
                log_structured(
                    "warning",
                    "Redis connection error in consumer loop",
                    stream=self.stream,
                    exc_info=True,
                )
                
                # Implement exponential backoff with shutdown check
                if not await self._backoff_and_check_shutdown():
                    break
                    
            except asyncio.CancelledError:
                log_structured("info", "Consumer loop cancelled", stream=self.stream)
                break
            except Exception:
                log_structured("error", "Unexpected error in consumer loop", stream=self.stream)
                break
                
        log_structured("info", "Consumer loop ended", stream=self.stream)

    async def _backoff_and_check_shutdown(self) -> bool:
        """Implement exponential backoff with shutdown checking. Returns False if shutdown requested."""
        # Calculate next backoff
        self._backoff = min(self._backoff * 2, self._max_backoff)
        
        log_structured(
            "info", 
            "Consumer backing off", 
            stream=self.stream, 
            backoff_seconds=self._backoff
        )
        
        # Wait for backoff with shutdown check
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._backoff)
        except asyncio.TimeoutError:
            # Backoff completed, continue loop
            return True
        except asyncio.CancelledError:
            # Shutdown requested
            return False
            
        # Shutdown event was set
        return False

    async def _safe_reclaim_stale(self) -> list[tuple[str, dict[str, Any]]]:
        """Safely reclaim stale messages with timeout and error handling."""
        try:
            return await asyncio.wait_for(
                self.bus.reclaim_stale(self.stream, self.group), timeout=3.0
            )
        except asyncio.TimeoutError:
            log_structured("warning", "Reclaim stale timeout", stream=self.stream)
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
        """Handle a single message with comprehensive error handling."""
        # Hard guard: enforce msg_id at ingestion boundary
        if "msg_id" not in data:
            raise RuntimeError(f"Invalid event: missing msg_id in {self.stream}")
        
        # V3 Schema Validation - Accept legacy and current versions
        schema_version = data.get("schema_version")
        if schema_version not in ACCEPTED_SCHEMA_VERSIONS:
            # Send invalid schema messages to DLQ immediately
            await self.dlq.push(
                self.stream, 
                msg_id, 
                data, 
                error=f"Invalid schema version: {schema_version}",
                retries=0
            )
            await self.bus.acknowledge(self.stream, self.group, msg_id)
            log_structured(
                "warning",
                "Invalid schema version sent to DLQ", 
                stream=self.stream, 
                message_id=msg_id,
                schema_version=schema_version
            )
            return
        
        send_to_dlq = False
        try:
            await self.process(data)
            await self.bus.acknowledge(self.stream, self.group, msg_id)
            log_structured(
                "debug", 
                "Message processed and acknowledged", 
                stream=self.stream, 
                message_id=msg_id,
                trace_id=data.get("trace_id")
            )
        except Exception as exc:  # noqa: BLE001
            try:
                send_to_dlq = await self.dlq.should_dlq(msg_id)
                if send_to_dlq:
                    retries_key = f"dlq:retries:{msg_id}"
                    retries = int(await self.dlq.redis.get(retries_key) or 0)
                    await self.dlq.push(self.stream, msg_id, data, error=str(exc), retries=retries)
                    await self.bus.acknowledge(self.stream, self.group, msg_id)
                    log_structured(
                        "warning", 
                        "Message sent to DLQ", 
                        stream=self.stream, 
                        message_id=msg_id, 
                        retries=retries,
                        trace_id=data.get("trace_id")
                    )
                else:
                    log_structured(
                        "warning", 
                        "Message processing failed, will retry", 
                        stream=self.stream, 
                        message_id=msg_id,
                        trace_id=data.get("trace_id")
                    )
            except (ConnectionError, TimeoutError) as redis_exc:
                log_structured(
                    "error",
                    "Redis error during DLQ handling",
                    stream=self.stream,
                    message_id=msg_id,
                    exc_info=True,
                )
            except Exception as dlq_exc:
                log_structured(
                    "error",
                    "DLQ handling failed",
                    stream=self.stream,
                    message_id=msg_id,
                    exc_info=True,
                )
            finally:
                log_structured(
                    "warning",
                    "Stream consumer failed to process message",
                    stream=self.stream,
                    message_id=msg_id,
                    exc_info=True,
                    dlq_sent=send_to_dlq,
                    trace_id=data.get("trace_id")
                )
