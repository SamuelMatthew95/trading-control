from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_STALE_THRESHOLD_SECONDS,
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_DLQ,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_GITHUB_PRS,
    STREAM_GRADED_DECISIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_MARKET_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_NOTIFICATIONS,
    STREAM_ORDERS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_SELL_REJECTED,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_LIFECYCLE,
    STREAM_TRADE_PERFORMANCE,
)
from api.database import AsyncSessionFactory
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.dashboard.learning import get_grade_history_payload
from api.services.dashboard.system import get_prices_payload
from api.services.llm_metrics import llm_metrics

MCP_STREAMS: tuple[str, ...] = (
    STREAM_MARKET_TICKS,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
    STREAM_ORDERS,
    STREAM_EXECUTIONS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_PERFORMANCE,
    STREAM_RISK_ALERTS,
    STREAM_LEARNING_EVENTS,
    STREAM_SYSTEM_METRICS,
    STREAM_AGENT_LOGS,
    STREAM_AGENT_GRADES,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_PROPOSALS,
    STREAM_NOTIFICATIONS,
    STREAM_GITHUB_PRS,
    STREAM_TRADE_LIFECYCLE,
    STREAM_DLQ,
    STREAM_SELL_REJECTED,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _safe_limit(value: int, *, default: int, max_value: int) -> int:
    if value <= 0:
        return default
    return min(value, max_value)


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    try:
        return datetime.fromisoformat(since.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _wrap(
    data: Any, *, source: str, degraded: bool = False, reason: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "degraded": degraded,
        "source": source,
        "generated_at": _now_iso(),
        "data": data,
    }
    if reason:
        payload["reason"] = reason
    return payload


def _redact_config_value(value: str | None) -> str | None:
    if value is None:
        return None
    return "***redacted***" if value.strip() else None


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return None
    path = parsed.path.strip("/")
    return f"{parsed.scheme}://{parsed.hostname}" + (f"/{path}" if path else "")


async def _db_heartbeat_rows(now_ts: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not is_db_available():
        return rows

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            text(
                """
                SELECT agent_name, status, last_seen, last_event, event_count, updated_at
                FROM agent_heartbeats
                ORDER BY last_seen DESC
                LIMIT 500
                """
            )
        )
        latest_by_name: dict[str, dict[str, Any]] = {}
        for row in result:
            m = dict(row._mapping)
            name = str(m.get("agent_name") or "").strip()
            if not name or name in latest_by_name:
                continue
            latest_by_name[name] = m

    for name in ALL_AGENT_NAMES:
        m = latest_by_name.get(name, {})
        last_seen_val = m.get("last_seen")
        try:
            last_seen = int(last_seen_val or 0)
        except (TypeError, ValueError):
            last_seen = 0
        age_seconds = max(0, now_ts - last_seen) if last_seen else None
        status = (
            "missing"
            if not m
            else (
                "stale" if age_seconds and age_seconds > AGENT_STALE_THRESHOLD_SECONDS else "active"
            )
        )
        rows.append(
            {
                "agent_name": name,
                "status": status,
                "last_heartbeat": (
                    m.get("updated_at").isoformat()
                    if hasattr(m.get("updated_at"), "isoformat")
                    else m.get("updated_at")
                ),
                "age_seconds": age_seconds,
                "source": "db",
                "metadata": {
                    "last_event": m.get("last_event"),
                    "event_count": m.get("event_count"),
                },
            }
        )
    return rows


async def get_agent_heartbeats_data() -> dict[str, Any]:
    now_ts = int(_now().timestamp())

    def _build_row(agent_name: str, raw: dict[str, Any], row_source: str) -> dict[str, Any]:
        last_seen = int(raw.get("last_seen") or 0)
        age_seconds = max(0, now_ts - last_seen) if last_seen else None
        if not raw:
            status = "missing"
        elif age_seconds is not None and age_seconds > AGENT_STALE_THRESHOLD_SECONDS:
            status = "stale"
        else:
            status = "active"
        return {
            "agent_name": agent_name,
            "status": status,
            "last_heartbeat": raw.get("updated_at") or raw.get("last_seen_at"),
            "age_seconds": age_seconds,
            "source": row_source,
            "metadata": {
                "last_event": raw.get("last_event"),
                "event_count": raw.get("event_count"),
                "version": raw.get("version"),
            },
        }

    try:
        redis_client = await get_redis()
        rows = []
        for name in ALL_AGENT_NAMES:
            raw = await redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=name))
            decoded = json.loads(raw) if raw else {}
            rows.append(_build_row(name, decoded, "redis"))
        return _wrap(
            {"agents": rows, "stale_threshold_seconds": AGENT_STALE_THRESHOLD_SECONDS},
            source="redis",
        )
    except Exception:
        try:
            db_rows = await _db_heartbeat_rows(now_ts)
            if db_rows:
                return _wrap(
                    {"agents": db_rows, "stale_threshold_seconds": AGENT_STALE_THRESHOLD_SECONDS},
                    source="db",
                    degraded=True,
                    reason="redis_unavailable_using_db",
                )
        except Exception:
            pass

        store = get_runtime_store()
        rows = [_build_row(name, store.get_agent(name) or {}, "memory") for name in ALL_AGENT_NAMES]
        return _wrap(
            {"agents": rows, "stale_threshold_seconds": AGENT_STALE_THRESHOLD_SECONDS},
            source="memory",
            degraded=True,
            reason="redis_unavailable",
        )


async def get_llm_health_data() -> dict[str, Any]:
    snap = llm_metrics.snapshot()
    success_rate = float(snap.get("success_rate_pct", 0.0))
    provider = {
        "provider": settings.LLM_PROVIDER,
        "enabled": True,
        "healthy": "healthy"
        if success_rate >= 80
        else ("unhealthy" if success_rate > 0 else "unknown"),
        "success_rate": success_rate,
        "error_rate": round(max(0.0, 100.0 - success_rate), 1),
        "average_latency_ms": snap.get("avg_latency_ms", 0.0),
        "p95_latency_ms": None,
        "rate_limit_count": snap.get("rate_limited_count", 0),
        "current_call_delay_ms": snap.get("effective_delay_ms", 0),
        "last_success_timestamp": None,
        "last_failure_timestamp": (snap.get("last_error") or {}).get("at"),
        "fallback_mode": bool(snap.get("grade_adjusted_delay", False)),
    }
    return _wrap({"providers": [provider]}, source="in_process")


async def get_agent_grades_data(
    *, limit: int = 20, agent_name: str | None = None, since: str | None = None
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, default=20, max_value=100)
    since_dt = _parse_since(since)

    payload = await get_grade_history_payload(safe_limit)
    rows = payload.get("grades", [])

    filtered: list[dict[str, Any]] = []
    for row in rows:
        name = row.get("agent_name") or row.get("agent")
        if agent_name and str(name or "").lower() != agent_name.lower():
            continue
        ts_raw = row.get("timestamp")
        ts_dt = _parse_since(str(ts_raw)) if ts_raw else None
        if since_dt:
            if ts_dt is None or ts_dt < since_dt:
                continue
        filtered.append(row)

    return _wrap(
        {"items": filtered, "total": len(filtered), "limit": safe_limit},
        source=payload.get("source", "db"),
        degraded=payload.get("source") == "in_memory",
    )


async def get_stream_lag_data() -> dict[str, Any]:
    try:
        redis_client = await get_redis()
        data: list[dict[str, Any]] = []
        for stream_name in MCP_STREAMS:
            try:
                stream_info = await redis_client.xinfo_stream(stream_name)
                groups = await redis_client.xinfo_groups(stream_name)
            except Exception:
                data.append({"stream": stream_name, "health": "unknown"})
                continue

            if not groups:
                data.append(
                    {
                        "stream": stream_name,
                        "length": stream_info.get("length"),
                        "last_generated_id": stream_info.get("last-generated-id"),
                        "group": None,
                        "pending": 0,
                        "lag": None,
                        "consumers": 0,
                        "last_delivered_id": None,
                        "health": "warning",
                    }
                )
                continue

            for group in groups:
                pending = int(group.get("pending", 0) or 0)
                lag = group.get("lag")
                health = "ok"
                if pending >= 1000:
                    health = "critical"
                elif pending >= 100:
                    health = "warning"
                data.append(
                    {
                        "stream": stream_name,
                        "length": stream_info.get("length"),
                        "last_generated_id": stream_info.get("last-generated-id"),
                        "group": group.get("name"),
                        "pending": pending,
                        "lag": lag,
                        "consumers": group.get("consumers", 0),
                        "last_delivered_id": group.get("last-delivered-id"),
                        "health": health,
                    }
                )
        return _wrap({"streams": data}, source="redis")
    except Exception:
        return _wrap({"streams": []}, source="memory", degraded=True, reason="redis_unavailable")


async def get_market_data_data(*, symbol: str | None = None, limit: int = 20) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, default=20, max_value=100)
    payload = await get_prices_payload()
    source = payload.get("source", "redis_cache")
    ticks = []
    now = _now()

    prices = payload.get("prices") or {}
    for sym, item in prices.items():
        if symbol and sym.lower() != symbol.lower():
            continue
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp")
        ts_dt = _parse_since(str(ts)) if ts else None
        age = int((now - ts_dt).total_seconds()) if ts_dt else None
        status = (
            "live" if age is not None and age <= 30 else ("stale" if age is not None else "unknown")
        )
        ticks.append(
            {
                "symbol": sym,
                "price": item.get("price"),
                "volume": item.get("volume"),
                "timestamp": ts,
                "age_seconds": age,
                "feed_status": status,
                "source": source,
            }
        )

    return _wrap(
        {"ticks": ticks[:safe_limit], "limit": safe_limit, "total": len(ticks)},
        source=source,
        degraded=source == "in_memory",
    )


async def get_positions_data() -> dict[str, Any]:
    if not is_db_available():
        return _wrap(
            {"positions": list(get_runtime_store().positions.values())},
            source="in_memory",
            degraded=True,
            reason="db_unavailable",
        )

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT symbol, quantity, avg_cost, last_price, unrealized_pnl, side, created_at, market_value
                    FROM positions
                    WHERE COALESCE(quantity, 0) != 0
                    ORDER BY updated_at DESC
                    LIMIT 200
                    """
                )
            )
            positions = [dict(row._mapping) for row in result]
        return _wrap({"positions": positions}, source="db")
    except Exception:
        return _wrap(
            {"positions": list(get_runtime_store().positions.values())},
            source="mixed",
            degraded=True,
            reason="positions_db_query_failed",
        )


def get_config_data() -> dict[str, Any]:
    data = {
        "environment": settings.NODE_ENV,
        "frontend_url": _safe_url(settings.FRONTEND_URL),
        "database": {
            "configured": bool(settings.DATABASE_URL),
            "url": _safe_url(str(settings.DATABASE_URL) if settings.DATABASE_URL else None),
        },
        "redis": {
            "configured": bool(settings.REDIS_URL),
            "url": _safe_url(settings.REDIS_URL),
        },
        "llm": {
            "provider": settings.LLM_PROVIDER,
            "openai_configured": bool(settings.OPENAI_API_KEY),
            "anthropic_configured": bool(settings.ANTHROPIC_API_KEY),
            "gemini_configured": bool(settings.GEMINI_API_KEY),
        },
        "broker": {
            "mode": settings.BROKER_MODE,
            "alpaca_configured": bool(settings.ALPACA_API_KEY and settings.ALPACA_SECRET_KEY),
            "alpaca_base_url": _safe_url(settings.ALPACA_BASE_URL),
        },
        "secrets": {
            "mcp_shared_token": _redact_config_value(settings.MCP_SHARED_TOKEN),
            "openai_api_key": _redact_config_value(settings.OPENAI_API_KEY),
            "anthropic_api_key": _redact_config_value(settings.ANTHROPIC_API_KEY),
            "gemini_api_key": _redact_config_value(settings.GEMINI_API_KEY),
        },
    }
    return _wrap(data, source="settings")
