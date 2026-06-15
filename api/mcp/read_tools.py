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
    REDIS_KEY_PAPER_POSITION,
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
    FieldName,
)
from api.database import AsyncSessionFactory
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.dashboard.learning import get_grade_history_payload
from api.services.dashboard.system import get_prices_payload
from api.services.llm_metrics import llm_metrics
from api.services.metrics_calc import closed_trade_stats
from api.services.redis_store import get_redis_store
from api.utils import now_iso

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

STREAMS_REQUIRING_ACTIVE_CONSUMERS: frozenset[str] = frozenset(
    {STREAM_SIGNALS, STREAM_DECISIONS, STREAM_ORDERS, STREAM_EXECUTIONS, STREAM_TRADE_LIFECYCLE}
)


def _flags_missing_consumer(stream_name: str, stream_length: int) -> bool:
    """Whether a stream with no active consumer should raise a warning.

    A required-consumer stream warns only when it actually holds messages. An
    empty / dormant stream (e.g. ``orders``, which is never written in the live
    pipeline) has nothing to consume, so a missing consumer is not a fault and
    must not raise a false ``no_active_consumers`` warning.
    """
    return stream_length > 0 and stream_name in STREAMS_REQUIRING_ACTIVE_CONSUMERS


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        "generated_at": now_iso(),
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
        if hasattr(last_seen_val, "timestamp"):
            last_seen = int(last_seen_val.timestamp())
        else:
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
            source="in_memory",
            degraded=True,
            reason="redis_unavailable",
        )


async def get_llm_health_data() -> dict[str, Any]:
    snap = llm_metrics.snapshot()
    success_rate = float(snap.get("success_rate_pct", 0.0))
    error_rate = round(max(0.0, 100.0 - success_rate), 1)
    last_success_timestamp = snap.get("last_success_at")
    last_failure_timestamp = (snap.get("last_error") or {}).get("at")
    enabled = True
    unhealthy = enabled and last_failure_timestamp and not last_success_timestamp
    degraded = bool(unhealthy or error_rate >= 50.0)
    provider = {
        "provider": settings.LLM_PROVIDER,
        "enabled": enabled,
        "healthy": "healthy"
        if success_rate >= 80
        else ("unhealthy" if success_rate > 0 else "unknown"),
        "success_rate": success_rate,
        "error_rate": error_rate,
        "average_latency_ms": snap.get("avg_latency_ms", 0.0),
        "p95_latency_ms": None,
        "rate_limit_count": snap.get("rate_limited_count", 0),
        "current_call_delay_ms": snap.get("effective_delay_ms", 0),
        "last_success_timestamp": last_success_timestamp,
        "last_failure_timestamp": last_failure_timestamp,
        "fallback_mode": bool(snap.get("grade_adjusted_delay", False)),
    }
    return _wrap(
        {"providers": [provider]},
        source="in_process",
        degraded=degraded,
        reason="llm_provider_unhealthy"
        if unhealthy
        else ("llm_provider_degraded" if degraded else None),
    )


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

            stream_length = int(stream_info.get("length") or 0)
            if not groups:
                missing_required_consumers = _flags_missing_consumer(stream_name, stream_length)
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
                        "health": "warning" if missing_required_consumers else "ok",
                        "reason": (
                            "no_active_consumers"
                            if missing_required_consumers
                            else "no_consumer_group"
                        ),
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
                consumers = int(group.get("consumers", 0) or 0)
                reason = None
                if consumers == 0 and _flags_missing_consumer(stream_name, stream_length):
                    health = "warning"
                    reason = "no_active_consumers"
                data.append(
                    {
                        "stream": stream_name,
                        "length": stream_info.get("length"),
                        "last_generated_id": stream_info.get("last-generated-id"),
                        "group": group.get("name"),
                        "pending": pending,
                        "lag": lag,
                        "consumers": consumers,
                        "last_delivered_id": group.get("last-delivered-id"),
                        "health": health,
                        "reason": reason,
                    }
                )
        return _wrap({"streams": data}, source="redis")
    except Exception:
        return _wrap({"streams": []}, source="in_memory", degraded=True, reason="redis_unavailable")


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
        positions = get_runtime_store().open_positions()
        return _wrap(
            {
                "positions": positions,
                "empty_reason": "fallback_hold_only" if not positions else None,
            },
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
        return _wrap(
            {
                "positions": positions,
                "empty_reason": "no_executed_trades" if not positions else None,
            },
            source="db",
        )
    except Exception:
        return _wrap(
            {"positions": get_runtime_store().open_positions()},
            source="mixed",
            degraded=True,
            reason="positions_db_query_failed",
        )


_EPS = 1e-9


async def _scan_broker_positions() -> dict[str, dict[str, Any]]:
    """SCAN the PaperBroker's Redis positions — the execution source of truth."""
    redis = await get_redis()
    pattern = REDIS_KEY_PAPER_POSITION.format(symbol="*")
    positions: dict[str, dict[str, Any]] = {}
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            symbol = str(parsed.get(FieldName.SYMBOL) or key.rsplit(":", 1)[-1])
            positions[symbol] = parsed
        if cursor == 0:
            break
    return positions


def _abs_qty(position: dict[str, Any]) -> float:
    try:
        return abs(float(position.get(FieldName.QTY) or 0.0))
    except (TypeError, ValueError):
        return 0.0


async def diagnose_positions_data() -> dict[str, Any]:
    """Reconcile the dashboard's store positions against the PaperBroker (truth).

    Flags: qty mismatches, store-only (stale) symbols, broker positions missing
    from the store mirror, and any flat (qty 0) rows lingering in the raw store.
    """
    broker = await _scan_broker_positions()
    broker_open = {s: p for s, p in broker.items() if _abs_qty(p) > _EPS}
    store = get_runtime_store()
    store_open = {str(p.get(FieldName.SYMBOL)): p for p in store.open_positions()}

    mismatches = []
    for symbol in sorted(set(broker_open) | set(store_open)):
        b_qty = _abs_qty(broker_open.get(symbol, {}))
        s_qty = _abs_qty(store_open.get(symbol, {}))
        if abs(b_qty - s_qty) > 1e-6:
            mismatches.append(
                {FieldName.SYMBOL: symbol, FieldName.BROKER_QTY: b_qty, FieldName.STORE_QTY: s_qty}
            )

    stale_store_only = sorted(set(store_open) - set(broker_open))
    missing_in_store = sorted(set(broker_open) - set(store_open))
    flat_in_raw_store = sorted(s for s, p in store.positions.items() if _abs_qty(p) <= _EPS)

    ok = not (mismatches or stale_store_only or missing_in_store or flat_in_raw_store)
    return _wrap(
        {
            FieldName.OK: ok,
            FieldName.BROKER_OPEN_COUNT: len(broker_open),
            FieldName.STORE_OPEN_COUNT: len(store_open),
            FieldName.MISMATCHES: mismatches,
            FieldName.STALE_STORE_ONLY: stale_store_only,
            FieldName.MISSING_IN_STORE: missing_in_store,
            FieldName.FLAT_IN_RAW_STORE: flat_in_raw_store,
        },
        source="redis",
        degraded=not ok,
    )


async def diagnose_trade_feed_data(limit: int = 500) -> dict[str, Any]:
    """Audit the advisory decision feed against holdings.

    A SELL for a symbol with no open long should appear as HOLD tagged
    ``downgrade_reason=sell_without_open_long``. ``untagged_phantom_sells`` is
    the bug indicator: a raw SELL still advertised for a symbol we don't hold.
    """
    redis_store = get_redis_store()
    if redis_store is None:
        return _wrap(
            {FieldName.WINDOW: 0},
            source="in_memory",
            degraded=True,
            reason="redis_store_unavailable",
        )
    decisions = await redis_store.list_decisions(limit=limit)
    broker = await _scan_broker_positions()
    held_long = {
        s
        for s, p in broker.items()
        if str(p.get(FieldName.SIDE) or "").lower() == "long" and _abs_qty(p) > _EPS
    }

    distribution: dict[str, int] = {}
    untagged_phantom_sells = 0
    downgraded_sells = 0
    for d in decisions:
        action = str(d.get(FieldName.ACTION) or "").lower() or "(blank)"
        distribution[action] = distribution.get(action, 0) + 1
        symbol = str(d.get(FieldName.SYMBOL) or "")
        if str(d.get(FieldName.DOWNGRADE_REASON) or "") == "sell_without_open_long":
            downgraded_sells += 1
        if action == "sell" and symbol not in held_long:
            untagged_phantom_sells += 1

    ok = untagged_phantom_sells == 0
    return _wrap(
        {
            FieldName.OK: ok,
            FieldName.WINDOW: len(decisions),
            FieldName.ACTION_DISTRIBUTION: distribution,
            FieldName.HELD_LONG_SYMBOLS: sorted(held_long),
            FieldName.DOWNGRADED_SELLS: downgraded_sells,
            FieldName.UNTAGGED_PHANTOM_SELLS: untagged_phantom_sells,
        },
        source="redis",
        degraded=not ok,
    )


def diagnose_metrics_data() -> dict[str, Any]:
    """Report the canonical realized-PnL / win-rate metrics from the order ledger.

    win_rate = winning / (winning + losing); opens (pnl=None) and zero-PnL
    scratches are excluded from the denominator.
    """
    orders = list(get_runtime_store().orders)
    stats = closed_trade_stats(orders)
    opens = sum(1 for o in orders if o.get(FieldName.PNL) in (None, ""))
    scratches = sum(
        1
        for o in orders
        if o.get(FieldName.PNL) not in (None, "") and float(o.get(FieldName.PNL) or 0.0) == 0.0
    )
    return _wrap(
        {
            FieldName.OK: True,
            FieldName.TOTAL_ORDERS: len(orders),
            FieldName.WINNING_TRADES: stats.winning,
            FieldName.LOSING_TRADES: stats.losing,
            FieldName.CLOSED_TRADES: stats.closed,
            FieldName.OPEN_TRADES_EXCLUDED: opens,
            FieldName.SCRATCH_TRADES_EXCLUDED: scratches,
            FieldName.REALIZED_PNL: stats.realized_pnl,
            FieldName.WIN_RATE: round(stats.win_rate, 4),
        },
        source="in_memory",
    )


async def diagnose_dashboard_consistency_data() -> dict[str, Any]:
    """Aggregate the position / trade-feed / metric / equity checks into one verdict."""
    positions = await diagnose_positions_data()
    trade_feed = await diagnose_trade_feed_data()
    metrics = diagnose_metrics_data()

    store = get_runtime_store()
    paired = store.paired_pnl_payload()[FieldName.SUMMARY]
    last_equity = store.equity_curve[-1] if store.equity_curve else None
    equity_realized = float(last_equity.get(FieldName.REALIZED_PNL)) if last_equity else 0.0
    realized = float(paired.get(FieldName.REALIZED_PNL) or 0.0)
    equity_consistent = (not store.equity_curve) or abs(equity_realized - realized) <= 1e-6

    issues: list[str] = []
    if not positions[FieldName.DATA][FieldName.OK]:
        issues.append("position_mismatch")
    if not trade_feed[FieldName.DATA][FieldName.OK]:
        issues.append("phantom_sells_in_feed")
    if not equity_consistent:
        issues.append("equity_curve_diverges_from_realized_pnl")

    overall_ok = not issues
    return _wrap(
        {
            FieldName.OK: overall_ok,
            FieldName.ISSUES: issues,
            FieldName.POSITIONS: positions[FieldName.DATA],
            FieldName.TRADE_FEED: trade_feed[FieldName.DATA],
            FieldName.METRICS: metrics[FieldName.DATA],
            FieldName.EQUITY_CONSISTENT: equity_consistent,
        },
        source="redis",
        degraded=not overall_ok,
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
            "mcp_shared_token": "***redacted***",
            "openai_api_key": _redact_config_value(settings.OPENAI_API_KEY),
            "anthropic_api_key": _redact_config_value(settings.ANTHROPIC_API_KEY),
            "gemini_api_key": _redact_config_value(settings.GEMINI_API_KEY),
        },
    }
    return _wrap(data, source="settings")
