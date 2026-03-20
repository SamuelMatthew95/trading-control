"""Dashboard WebSocket fanout."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])

STREAM_TYPE_MAP = {
    "market_ticks": "market_tick",
    "signals": "signal",
    "orders": "order_update",
    "executions": "order_update",
    "risk_alerts": "risk_alert",
    "learning_events": "learning_event",
    "system_metrics": "system_metric",
    "agent_logs": "agent_log",
}


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    redis_client = getattr(websocket.app.state, "redis_client", None)
    if redis_client is None:
        await websocket.close(code=1013)
        return
    last_ids = {stream: "$" for stream in STREAM_TYPE_MAP}
    try:
        while True:
            messages = await redis_client.xread(last_ids, block=1000, count=50)
            for stream_name, entries in messages:
                stream_key = stream_name.decode("utf-8") if isinstance(stream_name, bytes) else stream_name
                for entry_id, fields in entries:
                    payload_raw = fields.get("payload") or fields.get(b"payload") or "{}"
                    if isinstance(payload_raw, bytes):
                        payload_raw = payload_raw.decode("utf-8")
                    payload: dict[str, Any] = json.loads(payload_raw)
                    payload.setdefault("type", STREAM_TYPE_MAP.get(stream_key, stream_key))
                    await websocket.send_json(payload)
                    last_ids[stream_key] = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else entry_id
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
