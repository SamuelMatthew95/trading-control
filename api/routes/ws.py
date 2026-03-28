"""WebSocket endpoint for dashboard events."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.observability import log_structured

router = APIRouter(tags=["ws"])


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    broadcaster = getattr(websocket.app.state, "websocket_broadcaster", None)
    if broadcaster is None:
        await websocket.close(code=1013)
        return

    await broadcaster.add_connection(websocket)

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()})
            except WebSocketDisconnect:
                break
    except Exception as exc:  # noqa: BLE001
        log_structured(
            "error",
            "ws_connection_error",
            event_type="ws_connection_error",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )
    finally:
        await broadcaster.remove_connection(websocket)
