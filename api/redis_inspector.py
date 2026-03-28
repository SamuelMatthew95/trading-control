"""Debug endpoints for Redis + websocket pipeline visibility."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.config import settings
from api.events.bus import STREAMS
from api.observability import log_structured

router = APIRouter(prefix="/debug", tags=["debug"])


class TestEventRequest(BaseModel):
    stream: str = "market_ticks"
    payload: dict[str, Any] = {"message": "hello"}




def _mask_redis_url(url: str) -> str:
    if not url:
        return ""
    if "@" not in url:
        return url
    prefix, suffix = url.split("@", 1)
    if ":" in prefix:
        return f"{prefix.rsplit(':', 1)[0]}:****@{suffix}"
    return f"****@{suffix}"


@router.get("/redis")
async def debug_redis(request: Request) -> dict[str, Any]:
    redis_client = request.app.state.redis_client
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    pong = await redis_client.ping()
    return {
        "status": "ok" if pong else "error",
        "ping": bool(pong),
        "masked_url": _mask_redis_url(settings.REDIS_URL or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_error": getattr(getattr(request.app.state, "event_pipeline", None), "_last_error", None),
    }


@router.get("/agents")
async def debug_agents(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "agent_state", None)
    pipeline = getattr(request.app.state, "event_pipeline", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Agent registry unavailable")
    states = registry.snapshot()
    return {
        "agents": states,
        "count": len(states),
        "last_error": getattr(pipeline, "_last_error", None) if pipeline else None,
        "recent_activity": pipeline.status().get("recent", [])[:10] if pipeline else [],
    }

@router.get("/streams")
async def debug_streams(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    redis_client = request.app.state.redis_client
    pipeline = getattr(request.app.state, "event_pipeline", None)
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

    return {
        "streams": data,
        "limit": limit,
        "last_error": getattr(pipeline, "_last_error", None) if pipeline else None,
        "recent_activity": pipeline.status().get("recent", [])[:10] if pipeline else [],
    }


@router.get("/ws")
async def debug_ws(request: Request) -> dict[str, Any]:
    broadcaster = getattr(request.app.state, "websocket_broadcaster", None)
    pipeline = getattr(request.app.state, "event_pipeline", None)
    if broadcaster is None:
        raise HTTPException(status_code=503, detail="WebSocket broadcaster unavailable")
    return {
        "active_connections": broadcaster.active_connections,
        "messages_sent": broadcaster.messages_sent,
        "last_error": broadcaster.last_error,
        "recent_activity": pipeline.status().get("recent", [])[:10] if pipeline else [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/pipeline")
async def debug_pipeline(request: Request) -> dict[str, Any]:
    pipeline = getattr(request.app.state, "event_pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline unavailable")
    return pipeline.status()


@router.get("/dlq")
async def debug_dlq(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    dlq = getattr(request.app.state, "dlq_manager", None)
    pipeline = getattr(request.app.state, "event_pipeline", None)
    if dlq is None:
        raise HTTPException(status_code=503, detail="DLQ manager unavailable")
    events = await dlq.get_recent(limit=limit)
    return {
        "events": events,
        "count": len(events),
        "last_error": getattr(pipeline, "_last_error", None) if pipeline else None,
    }


@router.get("/dlq/stats")
async def debug_dlq_stats(request: Request) -> dict[str, Any]:
    dlq = getattr(request.app.state, "dlq_manager", None)
    pipeline = getattr(request.app.state, "event_pipeline", None)
    if dlq is None:
        raise HTTPException(status_code=503, detail="DLQ manager unavailable")
    stats = await dlq.stats()
    stats["recent_activity"] = pipeline.status().get("recent_failures", [])[:10] if pipeline else []
    return stats


@router.post("/publish-test-event")
async def publish_test_event(request: Request, payload: TestEventRequest) -> dict[str, Any]:
    bus = getattr(request.app.state, "event_bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="Event bus unavailable")

    msg_id = str(uuid.uuid4())
    event = {
        "type": "test_event",
        "msg_id": msg_id,
        "payload": payload.payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    redis_id = await bus.publish(payload.stream, event)

    return {
        "status": "published",
        "stream": payload.stream,
        "msg_id": msg_id,
        "redis_id": redis_id,
        "event": event,
    }
