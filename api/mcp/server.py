from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from api.runtime_state import is_db_available, runtime_mode
from api.services.dashboard.control import get_debug_state_payload
from api.services.dashboard.pnl import get_pnl_payload
from api.services.dashboard.trading import get_performance_trends_payload, get_trade_feed_payload
from api.services.redis_store import get_redis_store

mcp = FastMCP("trading-control", instructions="Read-only trading-control telemetry MCP server")
_base_mcp_app = mcp.http_app(path="/")


def _error_payload(message: str, *, details: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"status": "error", "error": message}
    if details:
        payload["details"] = details
    return payload


async def _safe_call(func: Callable[[], Awaitable[object]]) -> object:
    try:
        return await func()
    except Exception as exc:  # noqa: BLE001
        return _error_payload("unavailable", details=str(exc))


async def _get_decisions(limit: int = 50, action: str | None = None) -> dict[str, object]:
    try:
        store = get_redis_store()
        if store is None:
            return {"status": "unavailable", "reason": "redis_store_not_ready", "items": None}
        return {"status": "ok", "items": await store.list_decisions(limit=limit, action=action)}
    except Exception as exc:  # noqa: BLE001
        return _error_payload("unavailable", details=str(exc))


async def _get_notifications(limit: int = 50) -> dict[str, object]:
    try:
        store = get_redis_store()
        if store is None:
            return {"status": "unavailable", "reason": "redis_store_not_ready", "items": None}
        return {"status": "ok", "items": await store.list_notifications(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        return _error_payload("unavailable", details=str(exc))


def _debug_state_has_activity(debug_state: dict[str, object]) -> bool:
    """Determine activity from actual debug payload fields."""
    if bool(debug_state.get("has_data")):
        return True

    counts = debug_state.get("counts")
    if isinstance(counts, dict):
        for key in (
            "decisions",
            "notifications",
            "open_positions",
            "closed_trades",
            "equity_points",
        ):
            value = counts.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return True

    for key in (
        "latest_decision",
        "latest_notification",
        "latest_open_position",
        "latest_closed_trade",
    ):
        if debug_state.get(key) is not None:
            return True

    return False


@mcp.tool
async def get_service_health() -> dict[str, object]:
    return {
        "status": "ok",
        "db_available": is_db_available(),
        "persistence_mode": runtime_mode(),
    }


@mcp.tool
async def get_debug_state() -> dict[str, object]:
    data = await _safe_call(get_debug_state_payload)
    return data if isinstance(data, dict) else {"status": "ok", "data": data}


@mcp.tool
async def get_pnl() -> dict[str, object]:
    data = await _safe_call(get_pnl_payload)
    return data if isinstance(data, dict) else {"status": "ok", "data": data}


@mcp.tool
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, object]:
    async def _call() -> dict[str, object]:
        return await get_trade_feed_payload(limit=limit, session_id=session_id)

    data = await _safe_call(_call)
    return data if isinstance(data, dict) else {"status": "ok", "data": data}


@mcp.tool
async def get_performance_trends() -> dict[str, object]:
    data = await _safe_call(get_performance_trends_payload)
    return data if isinstance(data, dict) else {"status": "ok", "data": data}


@mcp.tool
async def get_decisions(limit: int = 50) -> dict[str, object]:
    return await _get_decisions(limit=limit)


@mcp.tool
async def get_notifications(limit: int = 50) -> dict[str, object]:
    return await _get_notifications(limit=limit)


@mcp.tool
async def get_health_summary() -> dict[str, object]:
    debug_state = await _safe_call(get_debug_state_payload)
    pnl = await _safe_call(get_pnl_payload)

    async def _feed() -> dict[str, object]:
        return await get_trade_feed_payload(limit=20, session_id=None)

    trade_feed = await _safe_call(_feed)
    decisions = await _get_decisions(limit=20)
    notifications = await _get_notifications(limit=20)
    return {
        "status": "ok",
        "service": {
            "db_available": is_db_available(),
            "persistence_mode": runtime_mode(),
        },
        "debug_state": debug_state,
        "pnl": pnl,
        "trade_feed": trade_feed,
        "decisions": decisions,
        "notifications": notifications,
    }


@mcp.tool
async def classify_health() -> dict[str, object]:
    debug_state_raw = await _safe_call(get_debug_state_payload)
    if not isinstance(debug_state_raw, dict) or debug_state_raw.get("status") == "error":
        return {
            "status": "ok",
            "classification": "unknown",
            "db_available": bool(is_db_available()),
            "reason": "debug_state_unavailable",
        }

    db_available = bool(is_db_available())
    has_activity = _debug_state_has_activity(debug_state_raw)

    if db_available and has_activity:
        classification = "healthy"
    elif not db_available and has_activity:
        classification = "expected_memory_mode_noise"
    elif db_available and not has_activity:
        classification = "code_bug_suspected"
    elif not has_activity:
        classification = "config_only"
    else:
        classification = "unknown"

    return {"status": "ok", "classification": classification, "db_available": db_available}


@asynccontextmanager
async def mcp_lifespan_context():
    """Expose FastMCP sub-app lifespan so parent FastAPI app can drive it."""
    router = getattr(_base_mcp_app, "router", None)
    if router is None or not hasattr(router, "lifespan_context"):
        yield
        return

    async with router.lifespan_context(_base_mcp_app):
        yield


mcp_app = _base_mcp_app
