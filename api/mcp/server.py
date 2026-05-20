from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

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
    return datetime.now(UTC).isoformat()


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


async def _safe_call(func: Callable[[], Awaitable[object]]) -> object:
    try:
        return await func()
    except Exception as exc:  # noqa: BLE001
        return _error_payload(f"unavailable:{exc}")


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
    except Exception as exc:  # noqa: BLE001
        return _error_payload(f"unavailable:{exc}", source="redis")


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
    except Exception as exc:  # noqa: BLE001
        return _error_payload(f"unavailable:{exc}", source="redis")


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
    return _envelope(
        ok=True,
        degraded=False,
        source="settings",
        data={"db_available": is_db_available(), "persistence_mode": runtime_mode()},
    )


@mcp.tool
async def get_debug_state() -> dict[str, object]:
    data = await _safe_call(get_debug_state_payload)
    if isinstance(data, dict) and "ok" in data and "data" in data:
        return data
    return _envelope(
        ok=True, degraded=False, source="in_memory", data=data if isinstance(data, dict) else {}
    )


@mcp.tool
async def get_pnl() -> dict[str, object]:
    data = await _safe_call(get_pnl_payload)
    if isinstance(data, dict) and "ok" in data and "data" in data:
        return data
    return _envelope(
        ok=True, degraded=False, source="in_memory", data=data if isinstance(data, dict) else {}
    )


@mcp.tool
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, object]:
    async def _call() -> dict[str, object]:
        return await get_trade_feed_payload(limit=limit, session_id=session_id)

    data = await _safe_call(_call)
    if isinstance(data, dict) and "ok" in data and "data" in data:
        return data
    return _envelope(
        ok=True, degraded=False, source="in_memory", data=data if isinstance(data, dict) else {}
    )


@mcp.tool
async def get_performance_trends() -> dict[str, object]:
    data = await _safe_call(get_performance_trends_payload)
    if isinstance(data, dict) and "ok" in data and "data" in data:
        return data
    return _envelope(
        ok=True, degraded=False, source="in_memory", data=data if isinstance(data, dict) else {}
    )


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
    return _envelope(
        ok=True,
        degraded=False,
        source="mixed",
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
async def classify_health() -> dict[str, object]:
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

    return _envelope(
        ok=True,
        degraded=False,
        source="in_process",
        data={"classification": classification, "db_available": db_available},
    )


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
