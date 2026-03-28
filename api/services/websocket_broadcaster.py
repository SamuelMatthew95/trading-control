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
        self._messages_sent = 0

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

    @property
    def messages_sent(self) -> int:
        return self._messages_sent

    async def add_connection(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)
        log_structured(
            "info",
            "ws_client_connected",
            event_name="ws_client_connected",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_connections=self.active_connections,
        )

    async def remove_connection(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        log_structured(
            "info",
            "ws_client_disconnected",
            event_name="ws_client_disconnected",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_connections=self.active_connections,
        )

    async def broadcast(self, data: dict[str, Any]) -> None:
        msg_id = str(data.get("msg_id", "none"))
        event_type = str(data.get("event_type", data.get("type", "unknown")))
        ts = str(data.get("timestamp", datetime.now(timezone.utc).isoformat()))

        disconnected: list[WebSocket] = []
        for websocket in self._connections:
            try:
                await websocket.send_json(data)
                self._messages_sent += 1
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                disconnected.append(websocket)
                log_structured(
                    "error",
                    "ws_client_send_failed",
                    event_name="ws_client_send_failed",
                    msg_id=msg_id,
                    event_type=event_type,
                    timestamp=ts,
                    exc_info=True,
                )

        for ws in disconnected:
            await self.remove_connection(ws)

        log_structured(
            "info",
            "websocket_broadcast",
            event_name="websocket_broadcast",
            msg_id=msg_id,
            event_type=event_type,
            timestamp=ts,
            active_connections=self.active_connections,
            messages_sent=self._messages_sent,
        )


_broadcaster: WebSocketBroadcaster | None = None


def get_broadcaster() -> WebSocketBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = WebSocketBroadcaster()
    return _broadcaster
