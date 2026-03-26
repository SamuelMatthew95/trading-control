"""Background stream consumer to push Redis events to WebSocket."""

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from api.events.bus import EventBus, STREAMS
from api.observability import log_structured


class StreamConsumer:
    """Background consumer that reads from Redis Streams and pushes to WebSocket."""
    
    def __init__(self, bus: EventBus, websocket_manager=None):
        self.bus = bus
        self.ws = websocket_manager
        self.running = False
        self._task = None
    
    async def start(self):
        """Start the background consumer loop."""
        if self.running:
            return
        
        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        log_structured("info", "stream_consumer_started", consumer="dashboard")
    
    async def stop(self):
        """Stop the background consumer loop."""
        self.running = False
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        log_structured("info", "stream_consumer_stopped")
    
    async def _run_loop(self):
        """Main consumer loop - reads from all streams and broadcasts."""
        log_structured("info", "stream_consumer_loop_started")
        
        log_structured(
            "info",
            "stream_consumer_config",
            streams=STREAMS,
            consumer="dashboard",
            group="workers"
        )
        
        while self.running:
            try:
                for stream in STREAMS:
                    if not self.running:
                        break
                    
                    # Consume messages with safety guard
                    try:
                        messages = await self.bus.consume(
                            stream,
                            group="workers",
                            consumer="dashboard",
                            count=10,
                            block_ms=100
                        )
                    except Exception as consume_err:
                        log_structured(
                            "error",
                            "redis_consume_failed",
                            stream=stream,
                            error=str(consume_err)
                        )
                        continue
                    
                    # Process and acknowledge messages
                    for msg_id, data in messages:
                        broadcast_success = False
                        
                        # Broadcast to WebSocket if manager exists
                        if self.ws and hasattr(self.ws, "broadcast"):
                            try:
                                # Determine message type based on stream
                                if stream == "system_metrics":
                                    msg_type = "system_metric"
                                else:
                                    msg_type = "event"
                                
                                # Unified format: always include 'type' for frontend routing
                                await self.ws.broadcast({
                                    "type": msg_type,
                                    "schema_version": "v3",
                                    "stream": stream,
                                    "message_id": msg_id,
                                    "data": data or {},
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
                                broadcast_success = True
                                log_structured(
                                    "info", "ws_event_sent",
                                    stream=stream,
                                    message_id=msg_id,
                                    msg_type=msg_type
                                )
                            except Exception as e:
                                log_structured(
                                    "warning", "ws_broadcast_failed",
                                    stream=stream, error=str(e)
                                )
                        
                        # Only ACK if broadcast was successful
                        if broadcast_success:
                            try:
                                await self.bus.acknowledge(stream, "workers", msg_id)
                            except Exception as ack_err:
                                log_structured(
                                    "error",
                                    "ack_failed",
                                    stream=stream,
                                    message_id=msg_id,
                                    error=str(ack_err)
                                )
                    
                    if messages:
                        log_structured(
                            "info",
                            "stream_batch_processed",
                            stream=stream,
                            batch_size=len(messages)
                        )
                
                # Small sleep to prevent tight loop
                await asyncio.sleep(0.1)
                
            except Exception as e:
                log_structured("error", "stream_consumer_loop_error", error=str(e))
                await asyncio.sleep(1)  # Back off on error
        
        log_structured("info", "stream_consumer_loop_ended")


# Global consumer instance
_consumer_instance: StreamConsumer | None = None


async def start_stream_consumer(bus: EventBus, websocket_manager=None):
    """Start the global stream consumer."""
    global _consumer_instance
    if _consumer_instance is None:
        _consumer_instance = StreamConsumer(bus, websocket_manager)
        await _consumer_instance.start()
        log_structured("info", "global_stream_consumer_started")


async def stop_stream_consumer():
    """Stop the global stream consumer."""
    global _consumer_instance
    if _consumer_instance:
        await _consumer_instance.stop()
        _consumer_instance = None
        log_structured("info", "global_stream_consumer_stopped")
