"""WebSocket broadcaster service for single Redis connection to multiple clients."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Set

from fastapi import WebSocket

from api.observability import log_structured


class WebSocketBroadcaster:
    """Manages WebSocket connections with a single Redis listener."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._broadcast_queue = asyncio.Queue()
        self._broadcast_task: asyncio.Task[None] | None = None
        self._redis_listener_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self, redis_client) -> None:
        """Start the broadcaster with Redis listener."""
        if self._running:
            return

        self._running = True
        self._redis_listener_task = asyncio.create_task(
            self._redis_listener(redis_client), name="redis-listener"
        )
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(), name="websocket-broadcaster"
        )
        log_structured("info", "WebSocket broadcaster started")

    async def stop(self) -> None:
        """Stop the broadcaster and clean up all connections."""
        self._running = False

        # Cancel background tasks
        if self._redis_listener_task is not None:
            self._redis_listener_task.cancel()
            try:
                await self._redis_listener_task
            except asyncio.CancelledError:
                pass
            self._redis_listener_task = None

        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
            self._broadcast_task = None

        # Close all WebSocket connections
        for ws in list(self._connections):
            try:
                await ws.close(code=1001)
            except Exception:
                pass
        self._connections.clear()

        log_structured("info", "WebSocket broadcaster stopped")

    async def add_connection(self, websocket: WebSocket) -> None:
        """Add a WebSocket connection to the broadcaster."""
        self._connections.add(websocket)
        log_structured(
            "info", "WebSocket connection added", total_connections=len(self._connections)
        )

    async def remove_connection(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the broadcaster."""
        self._connections.discard(websocket)
        log_structured(
            "info", "WebSocket connection removed", total_connections=len(self._connections)
        )

    async def _redis_listener(self, redis_client) -> None:
        """Single Redis listener that pushes data to broadcast queue."""
        if redis_client is None:
            log_structured("error", "Redis client not available for broadcaster")
            return

        last_ids = {
            "market_ticks": "$",
            "signals": "$",
            "orders": "$",
            "executions": "$",
            "risk_alerts": "$",
            "learning_events": "$",
            "system_metrics": "$",
            "agent_logs": "$",
        }

        stream_type_map = {
            "market_ticks": "market_tick",
            "signals": "signal",
            "orders": "order_update",
            "executions": "order_update",
            "risk_alerts": "risk_alert",
            "learning_events": "learning_event",
            "system_metrics": "system_metric",
            "agent_logs": "agent_log",
        }

        while self._running:
            try:
                messages = await asyncio.wait_for(
                    redis_client.xread(last_ids, block=1000, count=50), timeout=2.0
                )

                for stream_name, entries in messages:
                    stream_key = (
                        stream_name.decode("utf-8")
                        if isinstance(stream_name, bytes)
                        else stream_name
                    )

                    for entry_id, fields in entries:
                        payload_raw = fields.get("payload") or fields.get(b"payload") or "{}"
                        if isinstance(payload_raw, bytes):
                            payload_raw = payload_raw.decode("utf-8")

                        payload: dict[str, Any] = json.loads(payload_raw)
                        payload.setdefault("type", stream_type_map.get(stream_key, stream_key))

                        # Push to broadcast queue instead of sending directly
                        await self._broadcast_queue.put(payload)

                        last_ids[stream_key] = (
                            entry_id.decode("utf-8") if isinstance(entry_id, bytes) else entry_id
                        )

                await asyncio.sleep(0.05)

            except asyncio.TimeoutError:
                # Normal timeout, continue
                continue
            except Exception as exc:
                log_structured("error", "Redis listener error", error=str(exc))
                await asyncio.sleep(1.0)

    async def _broadcast_loop(self) -> None:
        """Broadcast messages to all connected WebSockets."""
        while self._running:
            try:
                # Get message from queue
                payload = await asyncio.wait_for(self._broadcast_queue.get(), timeout=1.0)

                # Send to all connected WebSockets
                disconnected = []
                for websocket in self._connections:
                    try:
                        await websocket.send_json(payload)
                    except Exception as exc:
                        log_structured(
                            "info", "WebSocket send failed, marking for removal", error=str(exc)
                        )
                        disconnected.append(websocket)

                # Remove disconnected WebSockets
                for ws in disconnected:
                    await self.remove_connection(ws)

            except asyncio.TimeoutError:
                # No messages to broadcast, continue
                continue
            except Exception as exc:
                log_structured("error", "Broadcast loop error", error=str(exc))
                await asyncio.sleep(0.1)


# Global singleton instance
_broadcaster: WebSocketBroadcaster | None = None


def get_broadcaster() -> WebSocketBroadcaster:
    """Get the global WebSocket broadcaster instance."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = WebSocketBroadcaster()
    return _broadcaster
