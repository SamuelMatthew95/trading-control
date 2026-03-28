"""Debug endpoints for Redis + websocket pipeline visibility."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from api.events.bus import STREAMS
from api.observability import log_structured

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/streams")
async def debug_streams(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    redis_client = request.app.state.redis_client
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")

    data: dict[str, list[dict[str, Any]]] = {}
    for stream in STREAMS:
        try:
            messages = await redis_client.xrevrange(stream, max="+", min="-", count=limit)
            parsed: list[dict[str, Any]] = []
            for msg_id, fields in messages:
                parsed.append(
                    {
                        "msg_id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        "fields": {
                            (k.decode() if isinstance(k, bytes) else str(k)): (
                                v.decode() if isinstance(v, bytes) else v
                            )
                            for k, v in fields.items()
                        },
                    }
                )
            data[stream] = parsed
        except Exception as exc:  # noqa: BLE001
            log_structured("error", "debug_stream_read_failed", stream=stream, error=str(exc))
            data[stream] = [{"error": str(exc)}]

    return {"streams": data, "limit": limit}


@router.get("/ws")
async def debug_ws(request: Request) -> dict[str, Any]:
    broadcaster = getattr(request.app.state, "websocket_broadcaster", None)
    if broadcaster is None:
        raise HTTPException(status_code=503, detail="WebSocket broadcaster unavailable")
    return {
        "active_clients": broadcaster.active_connections,
        "last_error": broadcaster.last_error,
    }


@router.get("/pipeline")
async def debug_pipeline(request: Request) -> dict[str, Any]:
    pipeline = getattr(request.app.state, "event_pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline unavailable")
    return pipeline.status()
