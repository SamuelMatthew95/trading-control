from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from api.mcp.read_tools import (
    diagnose_dashboard_consistency_data,
    diagnose_metrics_data,
    diagnose_positions_data,
    diagnose_trade_feed_data,
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
from api.utils import now_iso

mcp = FastMCP("trading-control", instructions="Read-only trading-control telemetry MCP server")
_base_mcp_app = mcp.http_app(path="/")
_CANONICAL_SOURCES = frozenset({"redis", "db", "in_memory", "mixed", "settings", "in_process"})


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
        "generated_at": now_iso(),
        "data": data,
    }
    if reason:
        payload["reason"] = reason
    return payload


def _error_payload(reason: str, *, source: str = "in_process") -> dict[str, object]:
    return _envelope(ok=False, degraded=True, source=source, reason=reason, data={})


def _normalize_source(source: object, *, default_source: str) -> tuple[str, str | None]:
    value = str(source or "").strip()
    if value in _CANONICAL_SOURCES:
        return value, None
    normalized = {
        "redis_hydrated": "in_memory",
        "db_error": "in_memory",
    }.get(value, default_source)
    reason = f"source_normalized:{value}" if value else None
    return normalized, reason


def _payload_degraded(payload: dict[str, object]) -> tuple[bool, str | None]:
    source_value = str(payload.get("source") or "").strip()
    if source_value in {"db_error", "redis_hydrated"}:
        return True, "component_degraded"
    if payload.get("empty_reason") == "db_degraded":
        return True, "component_degraded"
    return False, None


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
    source, normalization_reason = _normalize_source(
        payload.get("source"), default_source=default_source
    )
    degraded, degraded_reason = _payload_degraded(payload)
    data = dict(payload)
    if normalization_reason:
        data["upstream_source"] = str(payload.get("source") or "")
    return _envelope(
        ok=not degraded,
        degraded=degraded,
        source=source,
        reason=degraded_reason or normalization_reason,
        data=data,
    )


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
        notifications = await store.list_notifications(limit=limit)
        trace_ids = {
            str(entry.get("trace_id") or "").strip()
            for entry in notifications
            if isinstance(entry, dict) and str(entry.get("trace_id") or "").strip()
        }
        decision_map = await _build_decision_map_for_trace_ids(trace_ids)
        normalized = _normalize_notifications_with_decisions(notifications, decision_map)

        return _envelope(
            ok=True,
            degraded=False,
            source="redis",
            data={"items": normalized},
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


def _build_decision_map(decisions_payload: dict[str, object]) -> dict[str, dict[str, object]]:
    decision_items = decisions_payload.get("data", {}).get("items", [])
    decision_map: dict[str, dict[str, object]] = {}
    if isinstance(decision_items, list):
        for item in decision_items:
            if not isinstance(item, dict):
                continue
            trace_id = str(item.get("trace_id") or "").strip()
            if trace_id:
                decision_map[trace_id] = item
    return decision_map


async def _build_decision_map_for_trace_ids(trace_ids: set[str]) -> dict[str, dict[str, object]]:
    if not trace_ids:
        return {}
    decisions_payload = await _get_decisions(limit=10000)
    decision_map = _build_decision_map(decisions_payload)
    return {trace_id: decision_map[trace_id] for trace_id in trace_ids if trace_id in decision_map}


def _normalize_notification(
    entry: dict[str, object], decision_map: dict[str, dict[str, object]]
) -> dict[str, object]:
    if str(entry.get("type") or "") != "trade_signal":
        return entry
    trace_id = str(entry.get("trace_id") or "").strip()
    decision = decision_map.get(trace_id)
    if decision is None:
        return entry
    reason = str(decision.get("reason") or "").lower()
    reasoning_summary = str(decision.get("reasoning_summary") or "").lower()
    llm_succeeded = decision.get("llm_succeeded")
    is_fallback = (
        (llm_succeeded is False) or ("fallback" in reason) or ("fallback" in reasoning_summary)
    )
    if not is_fallback:
        return entry
    action_value = str(decision.get("action") or entry.get("action") or "").lower()
    symbol = str(decision.get("symbol") or entry.get("symbol") or "").strip()
    return {
        **entry,
        "type": "fallback_trade_blocked",
        "notification_type": "decision_degraded",
        "title": f"Fallback {action_value.upper()} decision — {symbol}"
        if symbol
        else "Fallback decision",
        "severity": "warning",
        "original_action": action_value,
        "action": "hold",
        "reason": str(decision.get("reason") or entry.get("reason") or "fallback"),
        "llm_succeeded": False,
    }


def _normalize_notifications_with_decisions(
    notifications: list[object], decision_map: dict[str, dict[str, object]]
) -> list[object]:
    normalized: list[object] = []
    for entry in notifications:
        if not isinstance(entry, dict):
            normalized.append(entry)
            continue
        normalized.append(_normalize_notification(entry, decision_map))
    return normalized


def _recent_decision_mode(decisions_payload: dict[str, object]) -> dict[str, object]:
    items = decisions_payload.get("data", {}).get("items", [])
    if not isinstance(items, list) or not items:
        return {}
    fallback_items = [
        i
        for i in items
        if isinstance(i, dict)
        and str(i.get("action") or "").lower() == "hold"
        and i.get("llm_succeeded") is False
        and "fallback" in str(i.get("reasoning_summary") or i.get("reason") or "").lower()
    ]
    if len(fallback_items) != len(items):
        return {}
    return {
        "decision_mode": "fallback_hold",
        "llm_succeeded_recently": False,
        "reasoning_status": "degraded",
    }


async def _get_service_health_impl() -> dict[str, object]:
    db_available = bool(is_db_available())
    return _envelope(
        ok=True,
        degraded=not db_available,
        source="mixed" if not db_available else "settings",
        reason="db_unavailable" if not db_available else None,
        data={"db_available": db_available, "persistence_mode": runtime_mode()},
    )


@mcp.tool
async def get_service_health() -> dict[str, object]:
    return await _get_service_health_impl()


_get_service_health_tool = _get_service_health_impl


async def _get_debug_state_impl() -> dict[str, object]:
    data = await _safe_call(get_debug_state_payload)
    wrapped = _wrap_payload(data, default_source="in_process")
    store = get_redis_store()
    if store is None:
        return wrapped
    data_payload = wrapped.get("data")
    if not isinstance(data_payload, dict):
        return wrapped
    latest_notification = data_payload.get("latest_notification")
    if not isinstance(latest_notification, dict):
        return wrapped
    trace_id = str(latest_notification.get("trace_id") or "").strip()
    decision_map = await _build_decision_map_for_trace_ids({trace_id} if trace_id else set())
    data_payload["latest_notification"] = _normalize_notification(latest_notification, decision_map)
    return wrapped


@mcp.tool
async def get_debug_state() -> dict[str, object]:
    return await _get_debug_state_impl()


_get_debug_state_tool = _get_debug_state_impl


async def _get_pnl_impl() -> dict[str, object]:
    data = await _safe_call(get_pnl_payload)
    wrapped = _wrap_payload(data, default_source="in_process")
    if wrapped.get("ok") is False:
        return wrapped
    payload = wrapped.get("data")
    if isinstance(payload, dict):
        if float(payload.get("total_pnl") or 0.0) == 0.0 and not payload.get("pnl"):
            payload.setdefault("empty_reason", "no_executed_trades")
    return wrapped


@mcp.tool
async def get_pnl() -> dict[str, object]:
    return await _get_pnl_impl()


_get_pnl_tool = _get_pnl_impl


async def _get_trade_feed_impl(limit: int = 50, session_id: str | None = None) -> dict[str, object]:
    async def _call() -> dict[str, object]:
        return await get_trade_feed_payload(limit=limit, session_id=session_id)

    data = await _safe_call(_call)
    wrapped = _wrap_payload(data, default_source="in_process")
    if wrapped.get("ok") is False:
        return wrapped
    payload = wrapped.get("data")
    if isinstance(payload, dict):
        if int(payload.get("count") or 0) == 0:
            payload.setdefault("empty_reason", "no_trade_lifecycle_events")
    return wrapped


@mcp.tool
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, object]:
    return await _get_trade_feed_impl(limit=limit, session_id=session_id)


_get_trade_feed_tool = _get_trade_feed_impl


async def _get_performance_trends_impl() -> dict[str, object]:
    data = await _safe_call(get_performance_trends_payload)
    wrapped = _wrap_payload(data, default_source="in_process")
    if wrapped.get("ok") is False:
        return wrapped
    payload = wrapped.get("data")
    if isinstance(payload, dict):
        summary = payload.get("summary") or {}
        if isinstance(summary, dict) and int(summary.get("total_trades") or 0) == 0:
            payload.setdefault("empty_reason", "no_trade_lifecycle_events")
    return wrapped


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
    debug_state = _wrap_payload(
        await _safe_call(get_debug_state_payload), default_source="in_process"
    )
    pnl = _wrap_payload(await _safe_call(get_pnl_payload), default_source="in_process")

    async def _feed() -> dict[str, object]:
        return await get_trade_feed_payload(limit=20, session_id=None)

    trade_feed = _wrap_payload(await _safe_call(_feed), default_source="in_process")
    decisions = await _get_decisions(limit=20)
    notifications = await _get_notifications(limit=20)
    decision_mode = _recent_decision_mode(decisions)
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
            **decision_mode,
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

    decision_mode = _recent_decision_mode(await _get_decisions(limit=20))
    degraded = (not db_available) or bool(decision_mode)
    return _envelope(
        ok=True,
        degraded=degraded,
        source="in_process",
        reason="db_unavailable"
        if not db_available
        else ("decision_reasoning_degraded" if decision_mode else None),
        data={"classification": classification, "db_available": db_available, **decision_mode},
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


@mcp.tool
async def diagnose_positions() -> dict[str, object]:
    """Reconcile dashboard store positions against the PaperBroker (source of truth)."""
    return await diagnose_positions_data()


@mcp.tool
async def diagnose_trade_feed() -> dict[str, object]:
    """Audit the advisory decision feed for phantom SELLs (unheld symbols)."""
    return await diagnose_trade_feed_data()


@mcp.tool
def diagnose_metrics() -> dict[str, object]:
    """Report canonical win-rate / realized-PnL from the order ledger."""
    return diagnose_metrics_data()


@mcp.tool
async def diagnose_dashboard_consistency() -> dict[str, object]:
    """One verdict: position mismatches, phantom sells, metric + equity consistency."""
    return await diagnose_dashboard_consistency_data()


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
