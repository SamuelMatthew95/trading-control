"""WebSocket endpoint for dashboard events."""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.constants import (
    AGENT_STALE_THRESHOLD_SECONDS,
    ALL_AGENT_NAMES,
    PIPELINE_STREAMS,
    REDIS_AGENT_STATUS_KEY,
    REDIS_KEY_PRICES,
    VALID_SYMBOLS,
    AgentStatus,
    FieldName,
)
from api.events.bus import STREAMS
from api.observability import log_structured
from api.runtime_state import get_runtime_store, runtime_mode

router = APIRouter(tags=["ws"])

_AGENT_NAMES = ALL_AGENT_NAMES

_PIPELINE_STREAMS = PIPELINE_STREAMS


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_in_memory_paired_pnl() -> dict[str, Any]:
    """Best-effort paired-PnL payload for WS fallback when DB is unavailable."""
    store = get_runtime_store()
    closed_trades = list(store.orders[-100:])
    winning_trades = sum(
        1 for order in closed_trades if (_safe_float(order.get(FieldName.PNL)) or 0.0) > 0
    )
    losing_trades = sum(
        1 for order in closed_trades if (_safe_float(order.get(FieldName.PNL)) or 0.0) < 0
    )
    open_positions = []
    for pos in store.positions.values():
        side = str(pos.get(FieldName.SIDE, "")).lower()
        qty = _safe_float(pos.get(FieldName.QTY))
        if side not in {"long", "short"} or qty is None or abs(qty) <= 0:
            continue
        open_positions.append(pos)
    realized_pnl = sum((_safe_float(order.get(FieldName.PNL)) or 0.0) for order in closed_trades)
    unrealized_pnl = sum(
        (_safe_float(pos.get(FieldName.UNREALIZED_PNL)) or 0.0) for pos in open_positions
    )
    total_trades = winning_trades + losing_trades
    return {
        "closed_trades": closed_trades,
        "open_positions": open_positions,
        "summary": {
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(realized_pnl + unrealized_pnl, 2),
            "closed_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate_percent": round(
                (winning_trades / total_trades * 100.0) if total_trades else 0.0, 2
            ),
            "open_positions": len(open_positions),
        },
    }


async def _build_db_snapshot(redis_client: Any = None) -> dict[str, Any]:
    """Fetch full dashboard state (DB rows + Redis prices) on WS connect.

    Returns a dashboard_update message matching the frontend DashboardData
    type — orders[], positions[], agent_logs[], prices{} — so every client
    starts with the same consistent view without any REST calls.
    """
    try:
        from api.database import AsyncSessionFactory
        from api.services.metrics_aggregator import MetricsAggregator

        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            data = await aggregator.get_raw_snapshot()
            # Paired PnL: closed trade pairs + open positions with unrealized PnL.
            # Included in the initial snapshot so the UI always has P&L data on
            # connect/reconnect without a separate REST fetch.
            try:
                data[FieldName.PNL] = await aggregator.get_paired_pnl(redis_client=redis_client)
            except Exception:
                log_structured("warning", "ws_snapshot_pnl_failed", exc_info=True)
                data[FieldName.PNL] = _build_in_memory_paired_pnl()
    except Exception:
        log_structured("warning", "ws_snapshot_db_unavailable", exc_info=True)
        data = get_runtime_store().dashboard_fallback_snapshot()
        data["mode"] = runtime_mode()
        data[FieldName.PNL] = _build_in_memory_paired_pnl()

    # Enrich with current prices from Redis cache
    if redis_client is not None:
        symbols = sorted(VALID_SYMBOLS)
        keys = [REDIS_KEY_PRICES.format(symbol=s) for s in symbols]
        try:
            cached_values = await redis_client.mget(keys)
            prices: dict[str, Any] = {}
            for symbol, raw in zip(symbols, cached_values, strict=False):
                if raw:
                    try:
                        prices[symbol] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        pass
            if prices:
                data["prices"] = prices
        except Exception:
            log_structured("warning", "ws_snapshot_prices_failed", exc_info=True)

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
        raw = await redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=name))
        if raw:
            data = json.loads(raw)
            last_seen = data.get(FieldName.LAST_SEEN, 0)
            age = now - last_seen
            status = (
                AgentStatus.STALE
                if age > AGENT_STALE_THRESHOLD_SECONDS
                else data.get(FieldName.STATUS, AgentStatus.ACTIVE)
            )
            agents.append(
                {
                    "name": name,
                    "status": status,
                    "event_count": data.get(FieldName.EVENT_COUNT, 0),
                    "last_event": data.get(FieldName.LAST_EVENT, ""),
                    "last_seen": last_seen,
                    "seconds_ago": age,
                }
            )
        else:
            agents.append(
                {
                    "name": name,
                    "status": AgentStatus.WAITING,
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
    # Register any streams not yet tracked. overwrite=False preserves the
    # broadcaster's existing read position — resetting to "$" on every new
    # client connection would cause the broadcaster to skip in-flight messages.
    for stream in STREAMS:
        register_result = broadcaster.register_stream(stream, "$", overwrite=False)
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
        db_snapshot = await _build_db_snapshot(redis_client)
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
