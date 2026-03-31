"""WebSocket endpoint for dashboard events."""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.events.bus import STREAMS
from api.observability import log_structured

router = APIRouter(tags=["ws"])

_AGENT_NAMES = [
    "SIGNAL_AGENT",
    "REASONING_AGENT",
    "GRADE_AGENT",
    "IC_UPDATER",
    "REFLECTION_AGENT",
    "STRATEGY_PROPOSER",
    "NOTIFICATION_AGENT",
]

_PIPELINE_STREAMS = ["market_events", "signals", "decisions", "graded_decisions"]


async def _build_db_snapshot() -> dict[str, Any]:
    """Fetch full dashboard state from DB via MetricsAggregator.

    All clients receive the same DB-backed state on connect, ensuring a
    consistent shared view regardless of when they join.
    """
    from api.database import AsyncSessionFactory
    from api.services.metrics_aggregator import MetricsAggregator

    async with AsyncSessionFactory() as session:
        aggregator = MetricsAggregator(session)
        data = await aggregator.get_dashboard_snapshot()

    return {
        "type": "dashboard_update",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _build_snapshot(redis_client: Any) -> dict[str, Any]:
    """Build agent-status + stream-metrics snapshot from Redis (no DB needed)."""
    now = int(datetime.now(timezone.utc).timestamp())
    agents = []
    for name in _AGENT_NAMES:
        raw = await redis_client.get(f"agent:status:{name}")
        if raw:
            data = json.loads(raw)
            last_seen = data.get("last_seen", 0)
            age = now - last_seen
            status = "STALE" if age > 120 else data.get("status", "ACTIVE")
            agents.append(
                {
                    "name": name,
                    "status": status,
                    "event_count": data.get("event_count", 0),
                    "last_event": data.get("last_event", ""),
                    "last_seen": last_seen,
                    "seconds_ago": age,
                }
            )
        else:
            agents.append(
                {
                    "name": name,
                    "status": "WAITING",
                    "event_count": 0,
                    "last_event": "",
                    "last_seen": 0,
                    "seconds_ago": 0,
                }
            )

    metrics: dict[str, int] = {}
    for stream_name in _PIPELINE_STREAMS:
        try:
            metrics[stream_name] = int(await redis_client.xlen(stream_name))
        except Exception:
            metrics[stream_name] = 0

    return {
        "type": "agent_status_update",
        "agents": agents,
        "metrics": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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
            {
                "type": "system",
                "status": "connected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception:
        pass

    # Send initial snapshots so the frontend never needs a REST fetch on load.
    # All clients receive the same data → shared consistent view.
    redis_client = getattr(websocket.app.state, "redis_client", None)
    if redis_client is not None:
        try:
            snapshot = await _build_snapshot(redis_client)
            await websocket.send_json(snapshot)
        except Exception:
            log_structured("warning", "ws_initial_snapshot_failed", exc_info=True)

    try:
        db_snapshot = await _build_db_snapshot()
        await websocket.send_json(db_snapshot)
    except Exception:
        log_structured("warning", "ws_db_snapshot_failed", exc_info=True)

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "system",
                        "status": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except WebSocketDisconnect:
                break
    except Exception:  # noqa: BLE001
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
