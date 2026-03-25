"""Background stream consumer to push Redis events to WebSocket."""

import asyncio
from contextlib import suppress
from typing import Any

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
        
        while self.running:
            try:
                for stream in STREAMS:
                    if not self.running:
                        break
                    
                    # Consume messages
                    messages = await self.bus.consume(
                        stream,
                        group="workers",
                        consumer="dashboard",
                        count=10,
                        block_ms=100  # Short block to check all streams frequently
                    )
                    
                    # Process and acknowledge messages
                    for msg_id, data in messages:
                        # Broadcast to WebSocket if manager exists
                        if self.ws:
                            try:
                                await self.ws.broadcast({
                                    "stream": stream,
                                    "message_id": msg_id,
                                    "data": data
                                })
                                log_structured(
                                    "info", "ws_event_sent",
                                    stream=stream,
                                    message_id=msg_id
                                )
                            except Exception as e:
                                log_structured(
                                    "warning", "ws_broadcast_failed",
                                    stream=stream, error=str(e)
                                )
                        
                        # Acknowledge message
                        await self.bus.acknowledge(stream, "workers", msg_id)
                
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
