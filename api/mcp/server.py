from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastmcp import FastMCP

from api.mcp.read_tools import (
    get_agent_grades_data,
    get_agent_heartbeats_data,
    get_config_data,
    get_llm_health_data,
    get_market_data_data,
    get_positions_data,
    get_stream_lag_data,
)
from api.runtime_state import is_db_available, runtime_mode
from api.services.dashboard.control import get_debug_state_payload
from api.services.dashboard.pnl import get_pnl_payload
from api.services.dashboard.trading import get_performance_trends_payload, get_trade_feed_payload
from api.services.redis_store import get_redis_store

mcp = FastMCP("trading-control", instructions="Read-only trading-control telemetry MCP server")
_base_mcp_app = mcp.http_app(path="/")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _envelope(
    *,
    ok: bool,
    degraded: bool,
    source: str,
    data: dict[str, object],
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": ok,
        "degraded": degraded,
        "source": source,
        "generated_at": _now_iso(),
        "data": data,
    }
    if reason:
        payload["reason"] = reason
    return payload


def _error_payload(reason: str, *, source: str = "in_process") -> dict[str, object]:
    return _envelope(ok=False, degraded=True, source=source, reason=reason, data={})


def _wrap_payload(payload: object, *, default_source: str = "in_process") -> dict[str, object]:
    if (
        isinstance(payload, dict)
        and "ok" in payload
        and "degraded" in payload
        and "data" in payload
    ):
        return payload
    if not isinstance(payload, dict):
        return _envelope(ok=True, degraded=False, source=default_source, data={})
    source = str(payload.get("source") or default_source)
    return _envelope(ok=True, degraded=False, source=source, data=payload)


async def _safe_call(func: Callable[[], Awaitable[object]]) -> object:
    try:
        return await func()
    except Exception:  # noqa: BLE001
        return _error_payload("mcp_tool_unavailable")


async def _get_decisions(limit: int = 50, action: str | None = None) -> dict[str, object]:
    try:
        store = get_redis_store()
        if store is None:
            return _envelope(
                ok=False,
                degraded=True,
                source="redis",
                reason="redis_store_not_ready",
                data={"items": []},
            )
        return _envelope(
            ok=True,
            degraded=False,
            source="redis",
            data={"items": await store.list_decisions(limit=limit, action=action)},
        )
    except Exception:  # noqa: BLE001
        return _error_payload("redis_unavailable", source="redis")


async def _get_notifications(limit: int = 50) -> dict[str, object]:
    try:
        store = get_redis_store()
        if store is None:
            return _envelope(
                ok=False,
                degraded=True,
                source="redis",
                reason="redis_store_not_ready",
                data={"items": []},
            )
        return _envelope(
            ok=True,
            degraded=False,
            source="redis",
            data={"items": await store.list_notifications(limit=limit)},
        )
    except Exception:  # noqa: BLE001
        return _error_payload("redis_unavailable", source="redis")


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


async def _get_service_health_impl() -> dict[str, object]:
    return _envelope(
        ok=True,
        degraded=False,
        source="settings",
        data={"db_available": is_db_available(), "persistence_mode": runtime_mode()},
    )


@mcp.tool
async def get_service_health() -> dict[str, object]:
    return await _get_service_health_impl()


_get_service_health_tool = _get_service_health_impl


async def _get_debug_state_impl() -> dict[str, object]:
    data = await _safe_call(get_debug_state_payload)
    return _wrap_payload(data, default_source="in_process")


@mcp.tool
async def get_debug_state() -> dict[str, object]:
    return await _get_debug_state_impl()


_get_debug_state_tool = _get_debug_state_impl


async def _get_pnl_impl() -> dict[str, object]:
    data = await _safe_call(get_pnl_payload)
    return _wrap_payload(data, default_source="in_process")


@mcp.tool
async def get_pnl() -> dict[str, object]:
    return await _get_pnl_impl()


_get_pnl_tool = _get_pnl_impl


async def _get_trade_feed_impl(limit: int = 50, session_id: str | None = None) -> dict[str, object]:
    async def _call() -> dict[str, object]:
        return await get_trade_feed_payload(limit=limit, session_id=session_id)

    data = await _safe_call(_call)
    return _wrap_payload(data, default_source="in_process")


@mcp.tool
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, object]:
    return await _get_trade_feed_impl(limit=limit, session_id=session_id)


_get_trade_feed_tool = _get_trade_feed_impl


async def _get_performance_trends_impl() -> dict[str, object]:
    data = await _safe_call(get_performance_trends_payload)
    return _wrap_payload(data, default_source="in_process")


@mcp.tool
async def get_performance_trends() -> dict[str, object]:
    return await _get_performance_trends_impl()


_get_performance_trends_tool = _get_performance_trends_impl


@mcp.tool
async def get_decisions(limit: int = 50) -> dict[str, object]:
    return await _get_decisions(limit=limit)


@mcp.tool
async def get_notifications(limit: int = 50) -> dict[str, object]:
    return await _get_notifications(limit=limit)


async def _get_health_summary_impl() -> dict[str, object]:
    debug_state = await _safe_call(get_debug_state_payload)
    pnl = await _safe_call(get_pnl_payload)

    async def _feed() -> dict[str, object]:
        return await get_trade_feed_payload(limit=20, session_id=None)

    trade_feed = await _safe_call(_feed)
    decisions = await _get_decisions(limit=20)
    notifications = await _get_notifications(limit=20)
    degraded = any(
        isinstance(child, dict) and child.get("ok") is False
        for child in (debug_state, pnl, trade_feed, decisions, notifications)
    )
    return _envelope(
        ok=not degraded,
        degraded=degraded,
        source="mixed",
        reason="component_unavailable" if degraded else None,
        data={
            "service": {"db_available": is_db_available(), "persistence_mode": runtime_mode()},
            "debug_state": debug_state,
            "pnl": pnl,
            "trade_feed": trade_feed,
            "decisions": decisions,
            "notifications": notifications,
        },
    )


@mcp.tool
async def get_health_summary() -> dict[str, object]:
    return await _get_health_summary_impl()


_get_health_summary_tool = _get_health_summary_impl


async def _classify_health_impl() -> dict[str, object]:
    debug_state_raw = await _safe_call(get_debug_state_payload)
    if not isinstance(debug_state_raw, dict) or (
        "ok" in debug_state_raw and not debug_state_raw.get("ok")
    ):
        return _envelope(
            ok=False,
            degraded=True,
            source="in_process",
            reason="debug_state_unavailable",
            data={"classification": "unknown", "db_available": bool(is_db_available())},
        )

    db_available = bool(is_db_available())
    debug_state = (
        debug_state_raw.get("data")
        if isinstance(debug_state_raw.get("data"), dict)
        else debug_state_raw
    )
    has_activity = _debug_state_has_activity(debug_state)

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

    return _envelope(
        ok=True,
        degraded=False,
        source="in_process",
        data={"classification": classification, "db_available": db_available},
    )


@mcp.tool
async def classify_health() -> dict[str, object]:
    return await _classify_health_impl()


_classify_health_tool = _classify_health_impl


@mcp.tool
async def get_agent_heartbeats() -> dict[str, object]:
    return await get_agent_heartbeats_data()


@mcp.tool
async def get_llm_health() -> dict[str, object]:
    return await get_llm_health_data()


@mcp.tool
async def get_agent_grades(
    limit: int = 20, agent_name: str | None = None, since: str | None = None
) -> dict[str, object]:
    return await get_agent_grades_data(limit=limit, agent_name=agent_name, since=since)


@mcp.tool
async def get_stream_lag() -> dict[str, object]:
    return await get_stream_lag_data()


@mcp.tool
async def get_market_data(symbol: str | None = None, limit: int = 20) -> dict[str, object]:
    return await get_market_data_data(symbol=symbol, limit=limit)


@mcp.tool
async def get_positions() -> dict[str, object]:
    return await get_positions_data()


@mcp.tool
def get_config() -> dict[str, object]:
    return get_config_data()


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
