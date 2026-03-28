"""WebSocket endpoint for dashboard events."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.events.bus import STREAMS
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
    for stream in STREAMS:
        register_result = broadcaster.register_stream(stream, "$")
        if inspect.isawaitable(register_result):
            await register_result
    try:
        await websocket.send_json(
            {"type": "system", "status": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
        )
    except Exception:
        # Continue loop; disconnect cleanup happens in finally block.
        pass

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "system", "status": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()})
            except WebSocketDisconnect:
                break
    except Exception as exc:  # noqa: BLE001
        log_structured(
            "error",
            "ws_connection_error",
            event_name="ws_connection_error",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            exc_info=True,
        )
    finally:
        await broadcaster.remove_connection(websocket)
