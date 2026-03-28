"""WebSocket broadcaster for a single event pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from api.observability import log_structured


class WebSocketBroadcaster:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._running = False
        self._last_error: str | None = None

    async def start(self, redis_client=None) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for ws in list(self._connections):
            try:
                await ws.close(code=1001)
            except Exception:
                pass
        self._connections.clear()

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def add_connection(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)
        log_structured(
            "info",
            "ws_client_connected",
            event_type="ws_client_connected",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_clients=self.active_connections,
        )

    async def remove_connection(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        log_structured(
            "info",
            "ws_client_disconnected",
            event_type="ws_client_disconnected",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_clients=self.active_connections,
        )

    async def broadcast(self, data: dict[str, Any]) -> None:
        disconnected: list[WebSocket] = []
        for websocket in self._connections:
            try:
                await websocket.send_json(data)
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                disconnected.append(websocket)

        for ws in disconnected:
            await self.remove_connection(ws)


_broadcaster: WebSocketBroadcaster | None = None


def get_broadcaster() -> WebSocketBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = WebSocketBroadcaster()
    return _broadcaster
