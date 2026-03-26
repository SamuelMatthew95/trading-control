"""WebSocket broadcaster service for real-time dashboard data."""

from __future__ import annotations

import asyncio
from typing import Any, Set

from fastapi import WebSocket

from api.observability import log_structured
from api.db import AsyncSessionFactory
from api.services.metrics_aggregator import MetricsAggregator


class WebSocketBroadcaster:
    """Manages WebSocket connections with dashboard data streaming."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._broadcast_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self, redis_client) -> None:
        """Start the broadcaster with dashboard data streaming."""
        if self._running:
            return

        self._running = True
        self._broadcast_task = asyncio.create_task(
            self._dashboard_broadcast_loop(), name="dashboard-broadcaster"
        )
        log_structured("info", "WebSocket broadcaster started")

    async def stop(self) -> None:
        """Stop the broadcaster and clean up all connections."""
        self._running = False

        # Cancel background task
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

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Broadcast data to all connected WebSockets."""
        if not self._connections:
            return

        # Ensure schema_version is present
        if "schema_version" not in data:
            data = {**data, "schema_version": "v3"}

        disconnected = []
        for websocket in self._connections:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)
        # Remove disconnected WebSockets
        for ws in disconnected:
            await self.remove_connection(ws)

    async def _dashboard_broadcast_loop(self) -> None:
        """Broadcast dashboard snapshots to all connected WebSockets."""
        while self._running:
            try:
                # Get dashboard snapshot from aggregator
                async with AsyncSessionFactory() as session:
                    aggregator = MetricsAggregator(session)
                    snapshot = await aggregator.get_dashboard_snapshot()

                # Send to all connected WebSockets
                disconnected = []
                for websocket in self._connections:
                    try:
                        await websocket.send_json({
                            "type": "dashboard_update",
                            "schema_version": "v3",
                            "timestamp": snapshot["timestamp"],
                            "data": snapshot
                        })
                    except Exception as exc:
                        log_structured(
                            "info", "WebSocket send failed, marking for removal", exc_info=True
                        )
                        disconnected.append(websocket)

                # Remove disconnected WebSockets
                for ws in disconnected:
                    await self.remove_connection(ws)

                # Wait before next update (2 seconds)
                await asyncio.sleep(2.0)

            except Exception:
                log_structured("error", "Dashboard broadcast loop error", exc_info=True)
                await asyncio.sleep(5.0)  # Wait longer on error


# Global singleton instance
_broadcaster: WebSocketBroadcaster | None = None


def get_broadcaster() -> WebSocketBroadcaster:
    """Get the global WebSocket broadcaster instance."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = WebSocketBroadcaster()
    return _broadcaster
