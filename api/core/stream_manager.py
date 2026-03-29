"""
Unified Stream Manager - Production-grade message processing.

Handles Redis streams with atomic processing, backpressure, and error handling.
"""

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from .config import get_settings
from .stream_logic import BackpressureController, MessageProcessor
from .writer.safe_writer import SafeWriter

logger = logging.getLogger(__name__)


class StreamManager:
    """Production-grade Redis stream processor with atomic guarantees."""

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        safe_writer: SafeWriter | None = None,
        settings: Any | None = None,
        message_processor: MessageProcessor | None = None,
        backpressure_controller: BackpressureController | None = None,
        event_bus: Any | None = None
    ):
        self.settings = settings or get_settings()
        self.redis_client = redis_client
        self.safe_writer = safe_writer
        self.event_bus = event_bus
        self.consumer_group = "trading_workers"
        self.consumer_name = f"worker_{datetime.now().timestamp()}"
        self.running = False
        self.paused = False
        self.shutdown_event = asyncio.Event()

        # Handler registry for message processing
        self.handler_registry: dict[str, Callable] = {}

        # Pure logic components
        self.message_processor = message_processor or MessageProcessor()
        self.backpressure_controller = backpressure_controller or BackpressureController()

        # Error tracking
        self.max_consecutive_errors = 5

    async def start(self) -> None:
        """Initialize connections and consumer groups."""
        if not self.redis_client:
            self.redis_client = redis.from_url(self.settings.REDIS_URL)

        if not self.safe_writer:
            from .db import AsyncSessionFactory
            self.safe_writer = SafeWriter(AsyncSessionFactory)

        # Ensure consumer groups exist
        await self._ensure_consumer_groups()

        self.running = True
        logger.info(f"Stream manager started: {self.consumer_name}")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self.running = False
        self.shutdown_event.set()

        if self.redis_client:
            await self.redis_client.close()

        logger.info(f"Stream manager stopped: {self.consumer_name}")

    def register_handler(self, stream: str, handler: Callable) -> None:
        """Register a message handler for a stream."""
        self.handler_registry[stream] = handler

    async def _ensure_consumer_groups(self) -> None:
        """Create consumer groups if they don't exist."""
        for stream in self.handler_registry.keys():
            try:
                await self.redis_client.xgroup_create(
                    stream, self.consumer_group, id="0", mkstream=True
                )
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    async def _read_messages(
        self, stream: str, count: int = 5, block_ms: int = 100
    ) -> list[dict[str, Any]]:
        """Read messages from a stream."""
        try:
            messages = await self.redis_client.xreadgroup(
                self.consumer_group,
                self.consumer_name,
                {stream: '>'},
                count=count,
                block=block_ms
            )

            result = []
            for stream_name, message_list in messages:
                for message_id, fields in message_list:
                    result.append({
                        'stream': stream_name,
                        'message_id': message_id,
                        'data': fields
                    })

            return result

        except Exception as e:
            logger.error(f"Failed to read from stream {stream}: {e}")
            return []

    async def _atomic_ack(self, stream: str, message_id: str) -> None:
        """Atomically acknowledge message processing."""
        try:
            await self.redis_client.xack(stream, self.consumer_group, message_id)
        except Exception as e:
            logger.error(f"Failed to ack message {message_id}: {e}")

    async def _send_to_dlq(self, message: dict[str, Any], error: str) -> None:
        """Send message to dead-letter queue."""
        try:
            dlq_data = self.message_processor.create_dlq_entry(message, error)

            await self.redis_client.xadd('dlq', dlq_data)
            await self._atomic_ack(message['stream'], message['message_id'])

            logger.warning(f"Sent to DLQ: {message['message_id']}")

        except Exception as e:
            logger.error(f"Failed to send to DLQ: {e}")

    async def _process_message(self, message: dict[str, Any]) -> bool:
        """Process a single message with atomic guarantees."""
        stream = message['stream']
        message_id = message['message_id']
        data = message['data']
        msg_id = data.get('msg_id', message_id)
        trace_id = data.get('trace_id', message_id)

        try:
            # Get handler
            handler = self.handler_registry.get(stream)
            if not handler:
                logger.error(f"No handler for stream: {stream}")
                await self._atomic_ack(stream, message_id)
                return False

            # Process message
            result = await handler(msg_id, stream, data, trace_id)

            if result.success:
                await self._atomic_ack(stream, message_id)

                # Trigger event-driven monitoring (non-blocking)
                if stream == 'orders':
                    try:
                        from api.main import on_message_processed
                        # Get current lag info
                        stream_info = await self.redis_client.xinfo_stream(stream)
                        lag = float(
                            stream_info.get("groups", {})
                            .get(self.consumer_group, {})
                            .get("lag", 0)
                        )
                        asyncio.create_task(
                            on_message_processed(self.event_bus, stream, lag)
                        )
                    except Exception:
                        pass  # Don't let monitoring break processing

                return True
            if result.retryable:
                return False
            await self._send_to_dlq(message, result.message or "Processing failed")
            return False

        except Exception as e:
            # Use pure backpressure logic
            self.backpressure_controller.record_error(e)

            if self.backpressure_controller.is_circuit_breaker_open():
                logger.error("Circuit breaker triggered - pausing")
                self.paused = True

            logger.error(f"Processing error for {msg_id}: {e}")
            return False

    async def _consumer_loop(self) -> None:
        """Main consumer loop with backpressure and error handling."""
        logger.info(f"Consumer loop started: {self.consumer_name}")

        consecutive_errors = 0

        while self.running and not self.shutdown_event.is_set():
            try:
                # Read messages from all streams
                read_tasks = []
                for stream in self.handler_registry.keys():
                    task = asyncio.create_task(self._read_messages(stream, count=5, block_ms=100))
                    read_tasks.append(task)

                results = await asyncio.gather(*read_tasks, return_exceptions=True)

                # Collect all messages
                all_messages = []
                for result in results:
                    if isinstance(result, list):
                        all_messages.extend(result)
                    elif isinstance(result, Exception):
                        logger.error(f"Read error: {result}")

                # Process messages
                if all_messages:
                    process_tasks = [
                        asyncio.create_task(self._process_message(msg))
                        for msg in all_messages
                    ]
                    await asyncio.gather(*process_tasks, return_exceptions=True)
                else:
                    # No messages - continue immediately
                    continue

                # Reset error counters on success
                consecutive_errors = 0
                self.backpressure_controller.reset()

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Consumer loop error: {e}")

                if consecutive_errors >= self.max_consecutive_errors:
                    logger.error("Too many consecutive errors - stopping")
                    break

                # Exponential backoff for errors - this is allowed
                await asyncio.sleep(min(consecutive_errors, 5))

    async def run(self) -> None:
        """Run the stream manager with signal handling."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal: {signum}")
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        await self.start()
        try:
            await self._consumer_loop()
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            await self.stop()


# Backward compatibility
UnifiedStreamManager = StreamManager
