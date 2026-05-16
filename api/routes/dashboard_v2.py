"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_EXECUTION,
    AGENT_STALE_THRESHOLD_SECONDS,
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_KILL_SWITCH_UPDATED_AT,
    REDIS_KEY_PRICES,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    REDIS_KEY_WORKER_HEARTBEAT,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    FieldName,
    LogType,
    OrderStatus,
    ProposalStatus,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available, runtime_mode
from api.schema_version import DASHBOARD_API_VERSION, DB_SCHEMA_VERSION
from api.services.agents.pipeline_agents import ChallengerAgent
from api.services.metrics_aggregator import MetricsAggregator
from api.services.redis_store import get_redis_store

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


async def hydrate_dashboard_state_from_redis() -> dict[str, Any]:
    """Hydrate runtime ledger from Redis decisions/notifications in DB-down mode."""
    store = get_runtime_store()
    diagnostics: dict[str, Any] = {
        FieldName.SOURCE: "in_memory",
        FieldName.HYDRATION_STATUS: "skipped",
        FieldName.PERSISTENCE_SOURCE: "memory_only",
        FieldName.LEDGER_SOURCE: "runtime_store",
        FieldName.REDIS_DECISIONS_SEEN: 0,
        FieldName.REDIS_NOTIFICATIONS_SEEN: 0,
        FieldName.REDIS_DECISIONS_APPLIED: 0,
        FieldName.REDIS_NOTIFICATIONS_APPLIED: 0,
        FieldName.APPLIED_DECISION_KEYS: len(store.applied_decision_keys),
        FieldName.LAST_ERROR: None,
    }
    if is_db_available():
        diagnostics[FieldName.PERSISTENCE_SOURCE] = "postgres"
        return diagnostics

    redis_store = get_redis_store()
    if redis_store is None:
        return diagnostics

    try:
        diagnostics[FieldName.HYDRATION_STATUS] = "attempted"
        decisions = await redis_store.list_decisions(limit=500)
        diagnostics[FieldName.REDIS_DECISIONS_SEEN] = len(decisions)
        decisions_before = len(store.applied_decision_keys)
        for decision in reversed(decisions):
            # Redis ``decisions:recent`` is advisory output from ReasoningAgent.
            # Replaying it as executed fills creates phantom positions/PnL.
            # Hydrate via advisory path only; portfolio mutation must come from
            # execution/fill sources.
            store.record_decision(decision)
        diagnostics[FieldName.REDIS_DECISIONS_APPLIED] = max(
            0, len(store.applied_decision_keys) - decisions_before
        )

        notifications = await redis_store.list_notifications(limit=500)
        diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN] = len(notifications)
        notifications_before = len(store.notifications)

        def _notification_key(item: dict[str, Any]) -> str:
            notif_id = str(
                item.get(FieldName.ID) or item.get(FieldName.NOTIFICATION_ID) or ""
            ).strip()
            if notif_id:
                return f"id:{notif_id}"
            trace_id = str(item.get(FieldName.TRACE_ID) or "").strip()
            notif_type = str(
                item.get(FieldName.TYPE) or item.get(FieldName.NOTIFICATION_TYPE) or ""
            ).strip()
            action = str(item.get(FieldName.ACTION) or "").strip().upper()
            symbol = str(item.get(FieldName.SYMBOL) or "").strip().upper()
            title = str(item.get(FieldName.TITLE) or "").strip()
            body = str(item.get(FieldName.BODY) or item.get(FieldName.MESSAGE) or "").strip()
            stable = "|".join([trace_id, notif_type, action, symbol, title, body])
            if stable.strip("|"):
                return f"stable:{stable}"
            return f"raw:{json.dumps(item, sort_keys=True, default=str)}"

        existing_notification_keys = {_notification_key(item) for item in store.notifications}
        for notification in reversed(notifications):
            notification_key = _notification_key(notification)
            if notification_key in existing_notification_keys:
                continue
            store.record_notification(notification)
            existing_notification_keys.add(notification_key)
        diagnostics[FieldName.REDIS_NOTIFICATIONS_APPLIED] = max(
            0, len(store.notifications) - notifications_before
        )

        diagnostics[FieldName.APPLIED_DECISION_KEYS] = len(store.applied_decision_keys)
        if (
            diagnostics[FieldName.REDIS_DECISIONS_SEEN] > 0
            or diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN] > 0
        ):
            diagnostics[FieldName.SOURCE] = "redis_hydrated"
            diagnostics[FieldName.PERSISTENCE_SOURCE] = "redis"
        diagnostics[FieldName.HYDRATION_STATUS] = "completed"
    except Exception as exc:
        diagnostics[FieldName.HYDRATION_STATUS] = "failed"
        diagnostics[FieldName.LAST_ERROR] = str(exc)
        log_structured("warning", "dashboard_redis_hydration_failed", exc_info=True)

    return diagnostics


def _attach_runtime_hydration_metadata(
    payload: dict[str, Any], diagnostics: dict[str, Any]
) -> dict[str, Any]:
    """Attach consistent hydration/source metadata to runtime payloads."""
    payload[FieldName.SOURCE] = diagnostics[FieldName.SOURCE]
    payload[FieldName.LEDGER_SOURCE] = diagnostics[FieldName.LEDGER_SOURCE]
    payload[FieldName.PERSISTENCE_SOURCE] = diagnostics[FieldName.PERSISTENCE_SOURCE]
    payload[FieldName.HYDRATION] = {
        "status": diagnostics[FieldName.HYDRATION_STATUS],
        FieldName.REDIS_DECISIONS_SEEN: diagnostics[FieldName.REDIS_DECISIONS_SEEN],
        FieldName.REDIS_DECISIONS_APPLIED: diagnostics[FieldName.REDIS_DECISIONS_APPLIED],
        FieldName.REDIS_NOTIFICATIONS_SEEN: diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN],
        FieldName.REDIS_NOTIFICATIONS_APPLIED: diagnostics[FieldName.REDIS_NOTIFICATIONS_APPLIED],
        FieldName.APPLIED_DECISION_KEYS: diagnostics[FieldName.APPLIED_DECISION_KEYS],
        FieldName.LAST_ERROR: diagnostics[FieldName.LAST_ERROR],
    }
    return payload


def _as_dict(payload: Any) -> dict[str, Any]:
    """Return payload as dict for mixed JSONB/text storage compatibility."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _in_memory_pnl_payload() -> dict[str, Any]:
    """Compute dashboard PnL metrics directly from in-memory runtime state."""
    store = get_runtime_store()
    orders = list(store.orders)
    open_positions = store.open_positions()
    total_pnl = sum(float(order.get(FieldName.PNL) or 0.0) for order in orders)
    wins = sum(1 for order in orders if float(order.get(FieldName.PNL) or 0.0) > 0)
    losses = sum(1 for order in orders if float(order.get(FieldName.PNL) or 0.0) < 0)
    equity_curve = list(store.equity_curve[-200:])

    return {
        "pnl": orders[-100:],
        FieldName.TOTAL_PNL: round(total_pnl, 2),
        FieldName.WINNING_TRADES: wins,
        FieldName.LOSING_TRADES: losses,
        "win_rate": round((wins / len(orders)) if orders else 0.0, 4),
        FieldName.ACTIVE_POSITIONS: len(open_positions),
        FieldName.BEST_TRADE: round(
            max((float(o.get(FieldName.PNL) or 0.0) for o in orders), default=0.0), 2
        ),
        FieldName.WORST_TRADE: round(
            min((float(o.get(FieldName.PNL) or 0.0) for o in orders), default=0.0), 2
        ),
        FieldName.EQUITY_CURVE: equity_curve,
        FieldName.HAS_DATA: bool(orders or open_positions or equity_curve),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


def _timestamp_from_agent_data(data: dict[str, Any], now: datetime) -> str | None:
    """Return an ISO timestamp from mixed heartbeat fields."""
    for key in ("started_at", "last_seen_at", FieldName.UPDATED_AT):
        value = data.get(key)
        if value:
            return str(value)

    last_seen = data.get(FieldName.LAST_SEEN)
    try:
        ts = float(last_seen)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _timestamp_to_iso(value: Any) -> str | None:
    """Normalize DB, memory, and epoch timestamps to an ISO string."""
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _in_memory_agent_instances_payload() -> dict[str, Any]:
    """Build agent instance rows from in-memory heartbeat state without touching Postgres."""
    store = get_runtime_store()
    now = datetime.now(timezone.utc)
    instances: list[dict[str, Any]] = []

    for name in ALL_AGENT_NAMES:
        data = store.get_agent(name) or {}
        status_raw = str(data.get(FieldName.STATUS) or "").strip().lower()
        if status_raw not in {"active", "running", "live"}:
            continue

        started_at = _timestamp_from_agent_data(data, now)
        last_seen = data.get(FieldName.LAST_SEEN)
        try:
            uptime_seconds = max(0, int(now.timestamp()) - int(float(last_seen)))
        except (TypeError, ValueError):
            uptime_seconds = 0

        instances.append(
            {
                FieldName.ID: str(data.get(FieldName.AGENT_ID) or f"memory:{name}"),
                FieldName.INSTANCE_KEY: str(
                    data.get(FieldName.INSTANCE_KEY) or name.lower().replace("_", "-")
                ),
                FieldName.POOL_NAME: str(data.get(FieldName.POOL_NAME) or name),
                "status": "active",
                FieldName.STARTED_AT: started_at,
                FieldName.RETIRED_AT: None,
                "event_count": int(data.get(FieldName.EVENT_COUNT) or 0),
                FieldName.UPTIME_SECONDS: uptime_seconds,
            }
        )

    return {
        FieldName.INSTANCES: instances,
        FieldName.ACTIVE_COUNT: len(instances),
        FieldName.RETIRED_COUNT: 0,
        "timestamp": now.isoformat(),
        "source": "in_memory",
    }


def _in_memory_proposals(limit: int = 20) -> list[dict[str, Any]]:
    """Return proposal events from the runtime store without opening a DB session."""
    safe_limit = max(1, min(limit, 200))
    proposals: list[dict[str, Any]] = []
    for event in get_runtime_store().get_events(limit=200):
        if event.get(FieldName.LOG_TYPE) != LogType.PROPOSAL:
            continue
        payload = _as_dict(event.get(FieldName.PAYLOAD))
        trace_id = (
            event.get(FieldName.TRACE_ID)
            or payload.get(FieldName.TRACE_ID)
            or payload.get(FieldName.REFLECTION_TRACE_ID)
            or payload.get(FieldName.MSG_ID)
        )
        proposal_id = str(trace_id or len(proposals) + 1)
        timestamp = _timestamp_to_iso(
            event.get(FieldName.CREATED_AT)
            or event.get(FieldName.TIMESTAMP)
            or payload.get(FieldName.TIMESTAMP)
        )
        proposals.append(
            {
                FieldName.ID: proposal_id,
                "symbol": payload.get(FieldName.SYMBOL),
                "action": payload.get(FieldName.ACTION),
                "grade_score": payload.get(FieldName.GRADE_SCORE),
                "bias": payload.get(FieldName.BIAS),
                FieldName.BUYS: payload.get(FieldName.BUYS),
                FieldName.SELLS: payload.get(FieldName.SELLS),
                "strategy_name": payload.get(FieldName.STRATEGY_NAME),
                "trace_id": trace_id,
                "created_at": timestamp,
                "source": "in_memory",
                "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                "proposal_type": payload.get(FieldName.PROPOSAL_TYPE, "parameter_change"),
                "content": payload.get(FieldName.CONTENT, {}),
                "requires_approval": payload.get(FieldName.REQUIRES_APPROVAL, True),
                "confidence": payload.get(FieldName.CONFIDENCE),
                "reflection_trace_id": payload.get(FieldName.REFLECTION_TRACE_ID),
                "timestamp": timestamp,
            }
        )
        if len(proposals) >= safe_limit:
            break
    return proposals


def _set_payload_status(record: dict[str, Any], status: str) -> None:
    payload = _as_dict(record.get(FieldName.PAYLOAD))
    payload[FieldName.STATUS] = status
    record[FieldName.PAYLOAD] = payload


def _proposal_matches(record: dict[str, Any], proposal_id: str) -> bool:
    payload = _as_dict(record.get(FieldName.PAYLOAD))
    candidates = {
        record.get(FieldName.ID),
        record.get(FieldName.TRACE_ID),
        record.get(FieldName.MSG_ID),
        payload.get(FieldName.TRACE_ID),
        payload.get(FieldName.REFLECTION_TRACE_ID),
        payload.get(FieldName.MSG_ID),
    }
    return proposal_id in {str(candidate) for candidate in candidates if candidate is not None}


def _update_in_memory_proposal_status(proposal_id: str, status: str) -> bool:
    store = get_runtime_store()
    updated = False
    for collection in (store.event_history, store.agent_logs):
        for record in collection:
            if record.get(FieldName.LOG_TYPE) == LogType.PROPOSAL and _proposal_matches(
                record, proposal_id
            ):
                _set_payload_status(record, status)
                updated = True
    return updated


def _in_memory_reflections(limit: int = 20) -> list[dict[str, Any]]:
    """Return reflection logs from memory in the learning endpoint shape."""
    safe_limit = max(1, min(limit, 200))
    rows = [
        row
        for row in reversed(
            get_runtime_store().agent_logs[-200:] + get_runtime_store().event_history[-200:]
        )
        if row.get(FieldName.LOG_TYPE) == LogType.REFLECTION
    ][:safe_limit]
    reflections = []
    for row in rows:
        payload = _as_dict(row.get(FieldName.PAYLOAD))
        timestamp = _timestamp_to_iso(
            row.get(FieldName.CREATED_AT)
            or row.get(FieldName.TIMESTAMP)
            or payload.get(FieldName.TIMESTAMP)
        )
        reflections.append(
            {
                "trace_id": row.get(FieldName.TRACE_ID) or payload.get(FieldName.TRACE_ID),
                "summary": payload.get(FieldName.SUMMARY, ""),
                FieldName.HYPOTHESES: payload.get(FieldName.HYPOTHESES, []),
                FieldName.WINNING_FACTORS: payload.get(FieldName.WINNING_FACTORS, []),
                FieldName.LOSING_FACTORS: payload.get(FieldName.LOSING_FACTORS, []),
                FieldName.REGIME_EDGE: payload.get(FieldName.REGIME_EDGE, {}),
                FieldName.FILLS_ANALYZED: payload.get(FieldName.FILLS_ANALYZED),
                "timestamp": timestamp,
            }
        )
    return reflections


def _in_memory_trace_payload(trace_id: str) -> dict[str, Any]:
    """Return trace details from memory without touching Postgres."""
    store = get_runtime_store()
    runs = [
        {
            FieldName.ID: str(row.get(FieldName.ID) or row.get(FieldName.MSG_ID) or trace_id),
            "agent_name": row.get(FieldName.AGENT_NAME) or row.get(FieldName.SOURCE),
            FieldName.RUN_TYPE: row.get(FieldName.RUN_TYPE),
            "status": row.get(FieldName.STATUS),
            "input_data": row.get(FieldName.INPUT_DATA),
            "output_data": row.get(FieldName.OUTPUT_DATA),
            "execution_time_ms": row.get(FieldName.EXECUTION_TIME_MS),
            "created_at": _timestamp_to_iso(row.get(FieldName.CREATED_AT)),
        }
        for row in store.agent_runs
        if row.get(FieldName.TRACE_ID) == trace_id
    ]
    logs = []
    for row in store.agent_logs + store.event_history:
        payload = _as_dict(row.get(FieldName.PAYLOAD))
        if row.get(FieldName.TRACE_ID) != trace_id and payload.get(FieldName.TRACE_ID) != trace_id:
            continue
        logs.append(
            {
                FieldName.ID: str(
                    row.get(FieldName.ID) or row.get(FieldName.MSG_ID) or len(logs) + 1
                ),
                "log_type": row.get(FieldName.LOG_TYPE) or payload.get(FieldName.LOG_TYPE),
                "payload": payload or row.get(FieldName.PAYLOAD),
                "created_at": _timestamp_to_iso(
                    row.get(FieldName.CREATED_AT) or row.get(FieldName.TIMESTAMP)
                ),
            }
        )
    grades = [
        {
            FieldName.ID: str(row.get(FieldName.ID) or row.get(FieldName.MSG_ID) or trace_id),
            "agent_id": str(row.get(FieldName.AGENT_ID) or row.get(FieldName.AGENT_NAME) or ""),
            "grade_type": row.get(FieldName.GRADE_TYPE) or row.get(FieldName.GRADE),
            "score": row.get(FieldName.SCORE) or row.get(FieldName.SCORE_PCT),
            "metrics": row.get(FieldName.METRICS, {}),
            "created_at": _timestamp_to_iso(
                row.get(FieldName.CREATED_AT) or row.get(FieldName.TIMESTAMP)
            ),
        }
        for row in store.grade_history
        if row.get(FieldName.TRACE_ID) == trace_id
    ]
    return {
        "trace_id": trace_id,
        FieldName.AGENT_RUNS: runs,
        FieldName.AGENT_LOGS: logs,
        FieldName.AGENT_GRADES: grades,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


def _performance_trends_empty_payload(
    *, source: str | None = None, error: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": {
            FieldName.TOTAL_PNL: 0.0,
            FieldName.TOTAL_TRADES: 0,
            "win_rate": 0.0,
            FieldName.AVG_WIN: 0.0,
            FieldName.AVG_LOSS: 0.0,
            FieldName.BEST_TRADE: 0.0,
            FieldName.WORST_TRADE: 0.0,
        },
        FieldName.DAILY_PNL: [],
        FieldName.GRADE_TREND: [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if source:
        payload[FieldName.SOURCE] = source
    if error:
        payload[FieldName.ERROR] = error
    return payload


@router.get("/snapshot")
async def get_dashboard_snapshot() -> dict[str, Any]:
    """
    Get complete dashboard snapshot with all metrics.

    This is the primary endpoint for the UI dashboard.
    Returns sanitized data with no NaN values.
    Uses in-memory store directly when the database is unavailable.
    """
    if not is_db_available():
        diagnostics = await hydrate_dashboard_state_from_redis()
        payload = get_runtime_store().dashboard_fallback_snapshot()
        return _attach_runtime_hydration_metadata(payload, diagnostics)
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_dashboard_snapshot()
    except Exception:
        log_structured("warning", "dashboard_snapshot_db_failed", exc_info=True)
        return get_runtime_store().dashboard_fallback_snapshot()


@router.get("/state")
async def get_dashboard_state() -> dict[str, Any]:
    """
    Get raw dashboard state in the format the frontend expects.

    Returns orders[], positions[], agent_logs[] — same shape as the WebSocket
    dashboard_update snapshot so the UI can hydrate via REST when the WebSocket
    is slow to connect or unavailable.
    """
    try:
        # Route determined once upfront; no silent try/except routing.
        if not is_db_available():
            diagnostics = await hydrate_dashboard_state_from_redis()
            store = get_runtime_store()
            data = store.dashboard_fallback_snapshot()
            data = _attach_runtime_hydration_metadata(data, diagnostics)
            data[FieldName.MODE] = runtime_mode()  # "in_memory_fallback" when DB is unavailable
        else:
            try:
                async with AsyncSessionFactory() as session:
                    aggregator = MetricsAggregator(session)
                    data = await aggregator.get_raw_snapshot()
            except Exception:
                log_structured("warning", "dashboard_state_db_failed", exc_info=True)
                fallback = get_runtime_store().dashboard_fallback_snapshot()
                fallback[FieldName.DEGRADED_MODE] = True
                fallback[FieldName.DEGRADED_REASON] = "db_unavailable"
                return fallback

        # Redis enrichment is best-effort: a Redis outage must not prevent
        # the frontend from receiving its DB-backed hydration data.
        try:
            redis_client = await get_redis()
        except Exception:
            log_structured("warning", "dashboard_state_redis_unavailable", exc_info=True)
            data.setdefault(FieldName.MODE, runtime_mode())
            db_up = is_db_available()
            data[FieldName.DEGRADED_MODE] = True
            data[FieldName.DEGRADED_REASON] = "db_unavailable" if not db_up else "redis_unavailable"
            return data

        # Enrich with current prices from Redis cache
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
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
                data[FieldName.PRICES] = prices
        except Exception:
            log_structured("warning", "dashboard_state_prices_failed", exc_info=True)

        # Enrich with IC weights from Redis
        try:
            raw_weights = await redis_client.get(REDIS_KEY_IC_WEIGHTS)
            if raw_weights:
                data[FieldName.IC_WEIGHTS] = json.loads(raw_weights)
        except Exception:
            log_structured("warning", "dashboard_state_ic_weights_failed", exc_info=True)

        # Enrich with agent heartbeats from Redis (keys must match what agents write)
        try:
            agent_keys = [REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES]
            agent_values = await redis_client.mget(agent_keys)
            agent_statuses: list[dict[str, Any]] = []
            for name, raw in zip(ALL_AGENT_NAMES, agent_values, strict=False):
                if raw:
                    try:
                        status = json.loads(raw)
                        agent_statuses.append({FieldName.NAME: name, **status})
                    except (json.JSONDecodeError, TypeError):
                        agent_statuses.append({FieldName.NAME: name, "status": "unknown"})
                else:
                    agent_statuses.append({FieldName.NAME: name, "status": "offline"})
            data[FieldName.AGENT_STATUSES] = agent_statuses
        except Exception:
            log_structured("warning", "dashboard_state_agent_statuses_failed", exc_info=True)

        data.setdefault(FieldName.MODE, runtime_mode())
        db_up = is_db_available()
        data[FieldName.DEGRADED_MODE] = not db_up
        if not db_up:
            data[FieldName.DEGRADED_REASON] = "db_unavailable"
        # Expose whether the configured LLM provider has an API key so the
        # frontend can surface a "rule-based mode" banner instead of silently
        # showing no reasoning decisions.
        provider = settings.LLM_PROVIDER.lower().strip()
        provider_key_map = {
            FieldName.GEMINI: getattr(settings, "GEMINI_API_KEY", None),
            FieldName.ANTHROPIC: getattr(settings, "ANTHROPIC_API_KEY", None),
            FieldName.OPENAI: getattr(settings, "OPENAI_API_KEY", None),
            FieldName.GROQ: getattr(settings, "GROQ_API_KEY", None),
        }
        llm_key = provider_key_map.get(provider) or ""
        data[FieldName.LLM_AVAILABLE] = bool(llm_key and llm_key.strip())
        data[FieldName.LLM_PROVIDER] = provider
        return data

    except Exception:
        log_structured("error", "dashboard state failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/stream-lag")
async def get_stream_lag() -> dict[str, Any]:
    """Get stream lag metrics per stream."""
    if not is_db_available():
        return {
            FieldName.STREAM_LAG: {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            lag_metrics = await aggregator.get_stream_lag_metrics()
            return {
                FieldName.STREAM_LAG: lag_metrics,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    except Exception:
        log_structured("warning", "stream_lag_db_unavailable", exc_info=True)
        return {
            FieldName.STREAM_LAG: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/system-health")
async def get_system_health() -> dict[str, Any]:
    """Get system health metrics."""
    if not is_db_available():
        return await MetricsAggregator(None, use_memory_store=True).get_system_health()

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_system_health()

    except Exception:
        log_structured("warning", "system_health_db_unavailable", exc_info=True)
        store = get_runtime_store()
        return {
            "status": "degraded",
            FieldName.MODE: runtime_mode(),
            FieldName.DB_HEALTH: store.last_health,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/pnl")
async def get_pnl_metrics() -> dict[str, Any]:
    """Get PnL metrics."""
    if not is_db_available():
        return _in_memory_pnl_payload()
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_pnl_metrics()

    except Exception:
        log_structured("warning", "pnl_metrics_db_unavailable", exc_info=True)
        return _in_memory_pnl_payload()


@router.get("/pnl/paired")
async def get_paired_pnl(request: Request) -> dict[str, Any]:
    """Paired P&L view: closed BUY→SELL pairs with realized PnL + open positions
    with live unrealized PnL enriched from the Redis price cache.

    Closed trades come from ``trade_lifecycle`` (one row per completed round-trip).
    Open positions are read from the ``positions`` table and enriched with current
    price so unrealized PnL updates on every request.
    """
    if not is_db_available():
        payload = get_runtime_store().paired_pnl_payload()
        return {
            FieldName.CLOSED_TRADES: payload[FieldName.CLOSED_TRADES],
            FieldName.OPEN_POSITIONS: payload[FieldName.OPEN_POSITIONS],
            "summary": payload[FieldName.SUMMARY],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    redis_client = getattr(request.app.state, "redis_client", None)
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_paired_pnl(redis_client=redis_client)
    except Exception:
        log_structured("warning", "paired_pnl_unavailable", exc_info=True)
        payload = get_runtime_store().paired_pnl_payload()
        return {
            FieldName.CLOSED_TRADES: payload[FieldName.CLOSED_TRADES],
            FieldName.OPEN_POSITIONS: payload[FieldName.OPEN_POSITIONS],
            "summary": payload[FieldName.SUMMARY],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/agents")
async def get_agent_metrics() -> dict[str, Any]:
    """Get agent activity metrics."""
    if not is_db_available():
        store = get_runtime_store()
        return {
            FieldName.AGENTS: [
                {
                    FieldName.NAME: name,
                    **({} if not store.get_agent(name) else store.get_agent(name)),
                }
                for name in ALL_AGENT_NAMES
            ],
            FieldName.RUNS: store.agent_runs[-50:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_agent_metrics()
    except Exception:
        log_structured("warning", "agent_metrics_db_failed", exc_info=True)
        store = get_runtime_store()
        return {
            FieldName.AGENTS: [
                {
                    FieldName.NAME: name,
                    **({} if not store.get_agent(name) else store.get_agent(name)),
                }
                for name in ALL_AGENT_NAMES
            ],
            FieldName.RUNS: store.agent_runs[-50:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/orders")
async def get_order_metrics() -> dict[str, Any]:
    """Get order flow metrics."""
    if not is_db_available():
        return await MetricsAggregator(None, use_memory_store=True).get_order_metrics()

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_order_metrics()

    except Exception:
        log_structured("warning", "order_metrics_db_unavailable", exc_info=True)
        return {
            FieldName.ORDERS: [],
            FieldName.TOTAL_ORDERS: 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/flow-status")
async def get_flow_status() -> dict[str, Any]:
    """Operational view to verify data is flowing end-to-end for UI/debugging."""
    try:
        if not is_db_available():
            store = get_runtime_store()
            mem_runs = len(store.agent_runs)
            return {
                FieldName.API_VERSION: DASHBOARD_API_VERSION,
                FieldName.DB_SCHEMA_VERSION: DB_SCHEMA_VERSION,
                FieldName.DEGRADED_MODE: True,
                FieldName.DEGRADED_REASON: "db_unavailable",
                FieldName.COUNTS: {
                    FieldName.AGENT_RUNS: mem_runs,
                    FieldName.AGENT_LOGS: len(store.event_history),
                    FieldName.AGENT_GRADES: len(store.grade_history),
                    FieldName.ORDERS: 0,
                    FieldName.TRADE_LIFECYCLE: 0,
                },
                FieldName.REALTIME_EVENT_COUNT: mem_runs,
                FieldName.PERSISTED_EVENT_COUNT: 0,
                FieldName.TRACE_COVERAGE: {"trace_id": None},
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "in_memory",
            }
        async with AsyncSessionFactory() as session:
            counts_sql = text("""
                SELECT
                    (SELECT COUNT(*) FROM agent_runs) AS agent_runs,
                    (SELECT COUNT(*) FROM agent_logs) AS agent_logs,
                    (SELECT COUNT(*) FROM agent_grades) AS agent_grades,
                    (SELECT COUNT(*) FROM orders) AS orders,
                    (SELECT COUNT(*) FROM trade_lifecycle) AS trade_lifecycle
            """)
            counts_row = (await session.execute(counts_sql)).mappings().first() or {}

            recent_trace_sql = text("""
                SELECT ar.trace_id
                FROM agent_runs ar
                WHERE ar.trace_id IS NOT NULL
                ORDER BY ar.created_at DESC
                LIMIT 1
            """)
            recent_trace = (await session.execute(recent_trace_sql)).scalar()

            trace_coverage = {
                "trace_id": recent_trace,
                FieldName.IN_AGENT_RUNS: 0,
                FieldName.IN_AGENT_LOGS: 0,
                FieldName.IN_TRADE_LIFECYCLE: 0,
            }
            if recent_trace:
                trace_coverage[FieldName.IN_AGENT_RUNS] = int(
                    (
                        await session.execute(
                            text("SELECT COUNT(*) FROM agent_runs WHERE trace_id = :t"),
                            {FieldName.T: recent_trace},
                        )
                    ).scalar()
                    or 0
                )
                trace_coverage[FieldName.IN_AGENT_LOGS] = int(
                    (
                        await session.execute(
                            text("SELECT COUNT(*) FROM agent_logs WHERE trace_id = :t"),
                            {FieldName.T: recent_trace},
                        )
                    ).scalar()
                    or 0
                )
                trace_coverage[FieldName.IN_TRADE_LIFECYCLE] = int(
                    (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*) FROM trade_lifecycle
                                WHERE execution_trace_id = :t
                                   OR decision_trace_id = :t
                                   OR signal_trace_id = :t
                                   OR grade_trace_id = :t
                                   OR reflection_trace_id = :t
                                """
                            ),
                            {FieldName.T: recent_trace},
                        )
                    ).scalar()
                    or 0
                )

        counts = {k: int(v or 0) for k, v in dict(counts_row).items()}
        return {
            FieldName.API_VERSION: DASHBOARD_API_VERSION,
            FieldName.DB_SCHEMA_VERSION: DB_SCHEMA_VERSION,
            FieldName.DEGRADED_MODE: False,
            FieldName.COUNTS: counts,
            FieldName.REALTIME_EVENT_COUNT: counts.get(FieldName.AGENT_RUNS, 0),
            FieldName.PERSISTED_EVENT_COUNT: counts.get(FieldName.AGENT_LOGS, 0),
            FieldName.TRACE_COVERAGE: trace_coverage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "flow_status_db_unavailable", exc_info=True)
        store = get_runtime_store()
        mem_runs = len(store.agent_runs)
        return {
            FieldName.API_VERSION: DASHBOARD_API_VERSION,
            FieldName.DB_SCHEMA_VERSION: DB_SCHEMA_VERSION,
            FieldName.DEGRADED_MODE: True,
            FieldName.DEGRADED_REASON: "db_unavailable",
            FieldName.COUNTS: {
                FieldName.AGENT_RUNS: mem_runs,
                FieldName.AGENT_LOGS: len(store.event_history),
                FieldName.AGENT_GRADES: len(store.grade_history),
                FieldName.ORDERS: 0,
                FieldName.TRADE_LIFECYCLE: 0,
            },
            FieldName.REALTIME_EVENT_COUNT: mem_runs,
            FieldName.PERSISTED_EVENT_COUNT: 0,
            FieldName.TRACE_COVERAGE: {"trace_id": None},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/prices")
async def get_prices() -> dict[str, Any]:
    """
    Get current market prices from Redis cache.

    This provides instant price data for dashboard initial load,
    without requiring WebSocket connection.
    """
    try:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
        redis_client = await get_redis()

        # Get all price keys from Redis
        keys = [REDIS_KEY_PRICES.format(symbol=symbol) for symbol in symbols]
        cached_values = await redis_client.mget(keys)

        prices = {}
        for symbol, cached_value in zip(symbols, cached_values, strict=False):
            if cached_value:
                try:
                    prices[symbol] = json.loads(cached_value)
                except json.JSONDecodeError:
                    log_structured("warning", "invalid price json", symbol=symbol)
                    prices[symbol] = None
            else:
                prices[symbol] = None

        return {
            FieldName.PRICES: prices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "redis_cache",
        }

    except Exception:
        log_structured("warning", "price_cache_redis_unavailable", exc_info=True)
        return {
            FieldName.PRICES: dict.fromkeys(
                ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/agents/status")
async def get_agents_status() -> dict[str, Any]:
    """Get agent status from Redis heartbeats, with in-memory fallback."""
    try:
        redis_client = await get_redis()
        now = int(datetime.now(timezone.utc).timestamp())
        heartbeat_map: dict[str, dict[str, Any]] = {}
        for name in ALL_AGENT_NAMES:
            raw = await redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=name))
            if raw:
                data = json.loads(raw)
                last_seen = data.get(FieldName.LAST_SEEN, 0)
                age = now - last_seen
                if age > AGENT_STALE_THRESHOLD_SECONDS:
                    status = "STALE"
                else:
                    status = data.get(FieldName.STATUS, "ACTIVE")
                heartbeat_map[name] = {
                    FieldName.NAME: name,
                    "status": status,
                    "event_count": data.get(FieldName.EVENT_COUNT, 0),
                    "last_event": data.get(FieldName.LAST_EVENT, ""),
                    "last_seen": last_seen,
                    "last_seen_at": datetime.fromtimestamp(last_seen, tz=timezone.utc).isoformat()
                    if last_seen
                    else None,
                    FieldName.SECONDS_AGO: age,
                }
            else:
                heartbeat_map[name] = {
                    FieldName.NAME: name,
                    "status": "WAITING",
                    "event_count": 0,
                    "last_event": "",
                    "last_seen": 0,
                    "last_seen_at": None,
                    FieldName.SECONDS_AGO: 0,
                }

        agents = list(heartbeat_map.values())
        if is_db_available():
            async with AsyncSessionFactory() as session:
                res = await session.execute(
                    text("""
                        SELECT instance_key, status, started_at, retired_at, event_count, metadata
                        FROM agent_instances
                        WHERE status IN ('active', 'retired')
                    """)
                )
                for row in res.all():
                    key = str(row[0] or "").upper().replace("-", "_")
                    existing = heartbeat_map.get(key)
                    if existing is None:
                        continue
                    meta = row[5] if isinstance(row[5], dict) else {}
                    existing[FieldName.INSTANCE_STATUS] = row[1]
                    existing[FieldName.STARTED_AT] = row[2].isoformat() if row[2] else None
                    existing[FieldName.RETIRED_AT] = row[3].isoformat() if row[3] else None
                    existing[FieldName.EVENT_COUNT] = max(
                        int(existing[FieldName.EVENT_COUNT]), int(row[4] or 0)
                    )
                    existing[FieldName.HEARTBEAT_COUNT] = int(
                        meta.get(FieldName.HEARTBEAT_COUNT) or 0
                    )
                    if existing[FieldName.STATUS] == "ACTIVE" and not existing.get(
                        FieldName.LAST_SEEN_AT
                    ):
                        existing[FieldName.STATUS] = "STALE"
                        existing[FieldName.LAST_EVENT] = "missing_last_seen_at"

        # Pipeline health summary: signal / decision stream lengths + EE last status
        pipeline_health: dict[str, Any] = {}
        try:
            pipeline_health[FieldName.SIGNAL_STREAM_LENGTH] = await redis_client.xlen(
                STREAM_SIGNALS
            )
            pipeline_health[FieldName.DECISION_STREAM_LENGTH] = await redis_client.xlen(
                STREAM_DECISIONS
            )
            _ee_raw = await redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=AGENT_EXECUTION))
            if _ee_raw:
                _ee = json.loads(_ee_raw)
                pipeline_health[FieldName.EE_LAST_STATUS] = _ee.get(FieldName.LAST_EVENT, "")
                pipeline_health[FieldName.EE_DECISIONS_EVALUATED] = int(
                    _ee.get(FieldName.EVENT_COUNT, 0)
                )
        except Exception:
            pass

        return {
            FieldName.AGENTS: agents,
            FieldName.PIPELINE_HEALTH: pipeline_health,
            FieldName.DEGRADED_MODE: not is_db_available(),
            **({FieldName.DEGRADED_REASON: "db_unavailable"} if not is_db_available() else {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "agents_status_redis_unavailable_using_memory", exc_info=True)
        store = get_runtime_store()
        now = int(datetime.now(timezone.utc).timestamp())
        agents = [
            {
                FieldName.NAME: name,
                "status": (store.get_agent(name) or {}).get(FieldName.STATUS, "WAITING"),
                "event_count": (store.get_agent(name) or {}).get(FieldName.EVENT_COUNT, 0),
                "last_event": (store.get_agent(name) or {}).get(FieldName.LAST_EVENT, ""),
                "last_seen": (store.get_agent(name) or {}).get(FieldName.LAST_SEEN, 0),
                FieldName.SECONDS_AGO: now
                - (store.get_agent(name) or {}).get(FieldName.LAST_SEEN, now),
            }
            for name in ALL_AGENT_NAMES
        ]
        return {
            FieldName.AGENTS: agents,
            FieldName.DEGRADED_MODE: True,
            FieldName.DEGRADED_REASON: "redis_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/system/metrics")
@router.get("/system-metrics")
async def get_system_stream_metrics() -> dict[str, Any]:
    """Get Redis stream lengths for pipeline health display."""
    try:
        redis_client = await get_redis()

        streams = {
            FieldName.MARKET_EVENTS: STREAM_MARKET_EVENTS,
            FieldName.SIGNALS: STREAM_SIGNALS,
            FieldName.DECISIONS: STREAM_DECISIONS,
            FieldName.GRADED_DECISIONS: STREAM_GRADED_DECISIONS,
        }

        result = {}
        for key, stream_name in streams.items():
            try:
                result[key] = await redis_client.xlen(stream_name)
            except Exception:
                result[key] = 0

        # agent_logs count from DB (skip if DB unavailable)
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    row = await session.execute(text("SELECT COUNT(*) FROM agent_logs"))
                    result[FieldName.AGENT_LOGS] = row.scalar() or 0
            except Exception:
                result[FieldName.AGENT_LOGS] = 0
        else:
            result[FieldName.AGENT_LOGS] = len(get_runtime_store().event_history)

        # trade_alerts count from events table (skip if DB unavailable)
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    row = await session.execute(
                        text("SELECT COUNT(*) FROM events WHERE event_type = 'trade.alert'")
                    )
                    result[FieldName.TRADE_ALERTS] = row.scalar() or 0
            except Exception:
                result[FieldName.TRADE_ALERTS] = 0
        else:
            result[FieldName.TRADE_ALERTS] = 0

        return {
            **result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "system_metrics_unavailable", exc_info=True)
        return {
            FieldName.MARKET_EVENTS: 0,
            FieldName.SIGNALS: 0,
            FieldName.DECISIONS: 0,
            FieldName.GRADED_DECISIONS: 0,
            FieldName.AGENT_LOGS: 0,
            FieldName.TRADE_ALERTS: 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/events/recent")
async def get_recent_events() -> dict[str, Any]:
    """Get last 10 events from events table, with in-memory fallback."""
    if not is_db_available():
        return {
            FieldName.EVENTS: get_runtime_store().get_events(limit=10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT id, event_type, entity_type, source, created_at
                    FROM events
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
            )
            rows = result.all()
            events = [
                {
                    FieldName.ID: str(row[0]),
                    "event_type": row[1],
                    "entity_type": row[2],
                    "source": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                }
                for row in rows
            ]
        return {
            FieldName.EVENTS: events,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "recent_events_db_unavailable", exc_info=True)
        store = get_runtime_store()
        return {
            FieldName.EVENTS: store.get_events(limit=10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/history/events")
async def get_event_history(limit: int = 50) -> dict[str, Any]:
    """Persisted event history + processed counts for operator visibility."""
    safe_limit = max(1, min(limit, 200))
    if not is_db_available():
        store = get_runtime_store()
        return {
            FieldName.STREAM_COUNTS: [],
            FieldName.PERSISTED_EVENTS: store.get_events(limit=safe_limit),
            FieldName.PERSISTED_LOGS: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }
    try:
        async with AsyncSessionFactory() as session:
            stream_counts = []
            try:
                counts_result = await session.execute(
                    text("""
                        SELECT
                            stream,
                            COUNT(*) AS processed_count,
                            MAX(created_at) AS last_processed_at
                        FROM processed_events
                        GROUP BY stream
                        ORDER BY processed_count DESC
                    """)
                )
                stream_counts = [
                    {
                        "stream": row[0],
                        FieldName.PROCESSED_COUNT: int(row[1] or 0),
                        FieldName.LAST_PROCESSED_AT: row[2].isoformat() if row[2] else None,
                    }
                    for row in counts_result.all()
                ]
            except Exception:
                stream_counts = []

            persisted_events = []
            try:
                events_result = await session.execute(
                    text("""
                        SELECT id, event_type, source, created_at
                        FROM events
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: safe_limit},
                )
                persisted_events = [
                    {
                        FieldName.ID: str(row[0]),
                        FieldName.KIND: row[1],
                        "source": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                    for row in events_result.all()
                ]
            except Exception:
                persisted_events = []

            persisted_logs = []
            try:
                logs_result = await session.execute(
                    text("""
                        SELECT id, trace_id, log_type, created_at
                        FROM agent_logs
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: safe_limit},
                )
                persisted_logs = [
                    {
                        FieldName.ID: str(row[0]),
                        "trace_id": row[1],
                        FieldName.KIND: row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                    for row in logs_result.all()
                ]
            except Exception:
                persisted_logs = []

        return {
            FieldName.STREAM_COUNTS: stream_counts,
            FieldName.PERSISTED_EVENTS: persisted_events,
            FieldName.PERSISTED_LOGS: persisted_logs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "event history failed", exc_info=True)
        if is_db_available():
            raise HTTPException(status_code=500, detail="Internal server error") from None
        store = get_runtime_store()
        return {
            FieldName.STREAM_COUNTS: [],
            FieldName.PERSISTED_EVENTS: store.get_events(limit=safe_limit),
            FieldName.PERSISTED_LOGS: [],
            "error": "event_history_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/health/worker")
async def get_worker_health() -> dict[str, Any]:
    """
    Check background worker health by examining price timestamps and heartbeat in Redis.

    Returns worker status based on how recently prices were updated and worker heartbeat.
    Uses HTTP status codes for Render health check integration:
    - 200: Healthy
    - 200: Degraded (still running but slow)
    - 200: Starting (within 60s grace period)
    - 503: Unhealthy (worker stopped/failing)
    """
    now = datetime.now(timezone.utc)

    # Check startup grace period (60 seconds)
    uptime_seconds = (now - PROCESS_START_TIME).total_seconds()
    if uptime_seconds < 60:
        return {
            "status": "starting",
            "message": "Worker is warming up",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }

    # After grace period, perform actual health checks
    try:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]

        # Try to get Redis client with timeout
        try:
            redis_client = await asyncio.wait_for(get_redis(), timeout=2.0)
        except asyncio.TimeoutError:
            log_structured("warning", "redis timeout during health check")
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": "Redis connection timeout",
                FieldName.CHECK_TIME: now.isoformat(),
            }
        except Exception as e:
            log_structured("warning", "redis connection failed during health check", exc_info=True)
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": str(e),
                FieldName.CHECK_TIME: now.isoformat(),
            }

        # Get all price keys and heartbeat from Redis with timeout
        keys = [REDIS_KEY_PRICES.format(symbol=symbol) for symbol in symbols] + [
            REDIS_KEY_WORKER_HEARTBEAT
        ]
        try:
            cached_values = await asyncio.wait_for(redis_client.mget(keys), timeout=2.0)
        except asyncio.TimeoutError:
            log_structured("warning", "redis mget timeout during health check")
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": "Redis read timeout",
                FieldName.CHECK_TIME: now.isoformat(),
            }
        except Exception as e:
            log_structured("warning", "redis read failed during health check", exc_info=True)
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": str(e),
                FieldName.CHECK_TIME: now.isoformat(),
            }

        # Extract heartbeat (last item)
        heartbeat_value = cached_values[-1]
        price_values = cached_values[:-1]

        timestamps = []
        stale_symbols = []

        # Check price timestamps
        for symbol, cached_value in zip(symbols, price_values, strict=False):
            if cached_value:
                try:
                    price_data = json.loads(cached_value)
                    timestamp_str = price_data.get(FieldName.TIMESTAMP)
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        timestamps.append(timestamp)

                        # Check if price is stale (older than 90 seconds)
                        if (now - timestamp).total_seconds() > 90:
                            stale_symbols.append(symbol)
                except (json.JSONDecodeError, ValueError):
                    stale_symbols.append(symbol)
            else:
                stale_symbols.append(symbol)

        # Check heartbeat
        heartbeat_age = None
        heartbeat_status = "missing"
        if heartbeat_value:
            try:
                heartbeat_time = datetime.fromisoformat(heartbeat_value.replace("Z", "+00:00"))
                heartbeat_age = (now - heartbeat_time).total_seconds()

                if heartbeat_age <= 10:
                    heartbeat_status = "healthy"
                elif heartbeat_age <= 30:
                    heartbeat_status = "degraded"
                else:
                    heartbeat_status = "stale"
            except ValueError:
                heartbeat_status = "invalid"

        if not timestamps:
            health_data = {
                "status": "unhealthy",
                "message": "No price data found in Redis",
                FieldName.LAST_UPDATE: None,
                FieldName.HEARTBEAT_STATUS: heartbeat_status,
                FieldName.HEARTBEAT_AGE: int(heartbeat_age) if heartbeat_age else None,
                FieldName.STALE_SYMBOLS: symbols,
                FieldName.TOTAL_SYMBOLS: len(symbols),
                FieldName.FRESH_SYMBOLS: 0,
                FieldName.UPTIME_SECONDS: uptime_seconds,
                FieldName.CHECK_TIME: now.isoformat(),
            }
            # Return 503 for unhealthy status
            raise HTTPException(status_code=503, detail=health_data)

        # Get the most recent timestamp
        last_update = max(timestamps)
        age_seconds = (now - last_update).total_seconds()

        # Determine overall health status
        if age_seconds <= 30 and heartbeat_status == "healthy":
            status = "healthy"
            message = "Worker is actively updating prices"
            http_status = 200
        elif age_seconds <= 90 and heartbeat_status in ["healthy", "degraded"]:
            status = "degraded"
            message = "Worker may be slow or experiencing issues"
            http_status = 200  # Still return 200 for degraded - worker is running
        else:
            status = "unhealthy"
            message = "Worker appears to be stopped or failing"
            http_status = 503

        health_data = {
            "status": status,
            "message": message,
            FieldName.LAST_UPDATE: last_update.isoformat(),
            FieldName.AGE_SECONDS: int(age_seconds),
            FieldName.HEARTBEAT_STATUS: heartbeat_status,
            FieldName.HEARTBEAT_AGE: int(heartbeat_age) if heartbeat_age else None,
            FieldName.STALE_SYMBOLS: stale_symbols if stale_symbols else None,
            FieldName.TOTAL_SYMBOLS: len(symbols),
            FieldName.FRESH_SYMBOLS: len(symbols) - len(stale_symbols),
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }

        # Return proper HTTP status for Render
        if http_status != 200:
            raise HTTPException(status_code=http_status, detail=health_data)

        return health_data

    except HTTPException:
        # Re-raise HTTP exceptions (our health check failures)
        raise
    except Exception as e:
        log_structured("error", "worker health check failed", exc_info=True)
        error_data = {
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }
        raise HTTPException(status_code=503, detail=error_data) from None


# ---------------------------------------------------------------------------
# Proposals panel (queries events table)
# ---------------------------------------------------------------------------


@router.get("/proposals")
async def list_proposals() -> dict[str, Any]:
    """Get recent strategy proposals.

    Prefer events-based proposals when available, but degrade gracefully on
    older schemas where the events table/columns do not exist.
    """
    if not is_db_available():
        return {
            FieldName.PROPOSALS: _in_memory_proposals(limit=20),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        proposals = []

        # Primary source for newer schemas.
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT
                            e.id,
                            COALESCE(
                                to_jsonb(e)->'data',
                                to_jsonb(e)->'payload',
                                '{}'::jsonb
                            ) AS payload,
                            e.created_at,
                            e.source
                        FROM events e
                        WHERE event_type = 'strategy.proposal'
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                )
                rows = result.all()
                for row in rows:
                    raw = row[1]
                    data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                    proposals.append(
                        {
                            FieldName.ID: str(row[0]),
                            "symbol": data.get(FieldName.SYMBOL),
                            "action": data.get(FieldName.ACTION),
                            "grade_score": data.get(FieldName.GRADE_SCORE),
                            "bias": data.get(FieldName.BIAS),
                            FieldName.BUYS: data.get(FieldName.BUYS),
                            FieldName.SELLS: data.get(FieldName.SELLS),
                            "strategy_name": data.get(FieldName.STRATEGY_NAME),
                            "trace_id": data.get(FieldName.TRACE_ID),
                            "created_at": row[2].isoformat() if row[2] else None,
                            "source": row[3],
                            "status": data.get(FieldName.STATUS, OrderStatus.PENDING),
                        }
                    )
        except Exception:
            # Compatibility fallback for deployments without events table.
            log_structured("warning", "proposals events query unavailable", exc_info=True)

        if not proposals:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT trace_id, payload, created_at
                        FROM agent_logs
                        WHERE log_type = :log_type
                        ORDER BY created_at DESC
                        LIMIT 20
                    """),
                    {"log_type": LogType.PROPOSAL},
                )
                for row in result.all():
                    payload = _as_dict(row[1])
                    proposals.append(
                        {
                            FieldName.ID: str(row[0]),
                            "symbol": payload.get(FieldName.SYMBOL),
                            "action": payload.get(FieldName.ACTION),
                            "grade_score": payload.get(FieldName.GRADE_SCORE),
                            "bias": payload.get(FieldName.BIAS),
                            FieldName.BUYS: payload.get(FieldName.BUYS),
                            FieldName.SELLS: payload.get(FieldName.SELLS),
                            "strategy_name": payload.get(FieldName.STRATEGY_NAME),
                            "trace_id": row[0],
                            "created_at": row[2].isoformat() if row[2] else None,
                            "source": "agent_logs",
                            "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                        }
                    )
        return {
            FieldName.PROPOSALS: proposals,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        return {
            FieldName.PROPOSALS: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as approved."""
    if not is_db_available():
        if not _update_in_memory_proposal_status(proposal_id, ProposalStatus.APPROVED):
            raise HTTPException(status_code=404, detail="Proposal not found") from None
        return {"status": ProposalStatus.APPROVED, FieldName.ID: proposal_id, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT id, data FROM events "
                        "WHERE id = :id AND event_type = 'strategy.proposal'"
                    ),
                    {FieldName.ID: proposal_id},
                )
                row = result.first()
                if not row:
                    raise HTTPException(status_code=404, detail="Proposal not found") from None
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                data[FieldName.STATUS] = "approved"
                await session.execute(
                    text("UPDATE events SET data = :data WHERE id = :id"),
                    {"data": json.dumps(data), FieldName.ID: proposal_id},
                )
        return {"status": "approved", FieldName.ID: proposal_id}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal approve failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as rejected."""
    if not is_db_available():
        if not _update_in_memory_proposal_status(proposal_id, ProposalStatus.REJECTED):
            raise HTTPException(status_code=404, detail="Proposal not found") from None
        return {"status": ProposalStatus.REJECTED, FieldName.ID: proposal_id, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT id, data FROM events "
                        "WHERE id = :id AND event_type = 'strategy.proposal'"
                    ),
                    {FieldName.ID: proposal_id},
                )
                row = result.first()
                if not row:
                    raise HTTPException(status_code=404, detail="Proposal not found") from None
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                data[FieldName.STATUS] = "rejected"
                await session.execute(
                    text("UPDATE events SET data = :data WHERE id = :id"),
                    {"data": json.dumps(data), FieldName.ID: proposal_id},
                )
        return {"status": "rejected", FieldName.ID: proposal_id}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal reject failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# Learning analytics
# ---------------------------------------------------------------------------


@router.get("/learning/proposals")
async def get_proposals(limit: int = 50) -> dict[str, Any]:
    """Get recent strategy proposals from agent_logs."""
    if not is_db_available():
        proposals = _in_memory_proposals(limit=limit)
        return {
            FieldName.PROPOSALS: proposals,
            FieldName.TOTAL: len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.PROPOSAL, FieldName.LIMIT: limit},
            )
            rows = result.all()
        proposals = []
        for row in rows:
            payload = _as_dict(row[1])
            proposals.append(
                {
                    FieldName.ID: row[0],
                    "proposal_type": payload.get(FieldName.PROPOSAL_TYPE, "parameter_change"),
                    "content": payload.get(FieldName.CONTENT, {}),
                    "requires_approval": payload.get(FieldName.REQUIRES_APPROVAL, True),
                    "confidence": payload.get(FieldName.CONFIDENCE),
                    "reflection_trace_id": payload.get(FieldName.REFLECTION_TRACE_ID),
                    "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
            )

        # Backward compatibility: some deployments store proposals in events only.
        if not proposals:
            try:
                async with AsyncSessionFactory() as session:
                    fallback_result = await session.execute(
                        text("""
                            SELECT
                                e.id,
                                COALESCE(
                                    to_jsonb(e)->'data',
                                    to_jsonb(e)->'payload',
                                    '{}'::jsonb
                                ) AS payload,
                                e.created_at
                            FROM events e
                            WHERE event_type = 'strategy.proposal'
                            ORDER BY created_at DESC
                            LIMIT :limit
                        """),
                        {FieldName.LIMIT: limit},
                    )
                    for row in fallback_result.all():
                        data = _as_dict(row[1])
                        proposals.append(
                            {
                                FieldName.ID: str(row[0]),
                                "proposal_type": data.get(
                                    FieldName.PROPOSAL_TYPE, "strategy_proposal"
                                ),
                                "content": data,
                                "requires_approval": True,
                                "confidence": data.get(FieldName.CONFIDENCE),
                                "reflection_trace_id": data.get(FieldName.TRACE_ID),
                                "status": data.get(FieldName.STATUS, OrderStatus.PENDING),
                                "timestamp": row[2].isoformat() if row[2] else None,
                            }
                        )
            except Exception:
                log_structured(
                    "warning",
                    "learning proposals events fallback unavailable",
                    exc_info=True,
                )
        return {
            FieldName.PROPOSALS: proposals,
            FieldName.TOTAL: len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        return {
            FieldName.PROPOSALS: [],
            FieldName.TOTAL: 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/learning/grades")
async def get_grade_history(limit: int = 50) -> dict[str, Any]:
    """Get recent agent grade history from agent_grades table and agent_logs."""
    if not is_db_available():
        store = get_runtime_store()
        grades = store.get_grades(limit=limit)
        return {
            FieldName.GRADES: grades,
            FieldName.TOTAL: len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.GRADE, FieldName.LIMIT: limit},
            )
            rows = result.all()
        grades = []
        for row in rows:
            payload = _as_dict(row[1])
            grades.append(
                {
                    "trace_id": row[0],
                    "grade": payload.get(FieldName.GRADE),
                    "score": payload.get(FieldName.SCORE),
                    "score_pct": payload.get(FieldName.SCORE_PCT),
                    "metrics": payload.get(FieldName.METRICS, {}),
                    FieldName.FILLS_GRADED: payload.get(FieldName.FILLS_GRADED),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
            )

        # Backward compatibility: older deployments only write agent_grades rows.
        if not grades:
            async with AsyncSessionFactory() as session:
                fallback_result = await session.execute(
                    text("""
                        SELECT trace_id, score, metrics, created_at
                        FROM agent_grades
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: limit},
                )
                for row in fallback_result.all():
                    metrics = _as_dict(row[2])
                    score = float(row[1]) if row[1] is not None else None
                    grades.append(
                        {
                            "trace_id": row[0],
                            "grade": None,
                            "score": score,
                            "score_pct": round(score, 2) if score is not None else None,
                            "metrics": metrics,
                            FieldName.FILLS_GRADED: metrics.get(FieldName.FILLS_GRADED),
                            "timestamp": row[3].isoformat() if row[3] else None,
                        }
                    )
        return {
            FieldName.GRADES: grades,
            FieldName.TOTAL: len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "grades fetch failed", exc_info=True)
        if is_db_available():
            raise HTTPException(status_code=500, detail="Internal server error") from None
        store = get_runtime_store()
        grades = store.get_grades(limit=limit)
        return {
            FieldName.GRADES: grades,
            FieldName.TOTAL: len(grades),
            "error": "grades_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/learning/ic-weights")
async def get_ic_weights() -> dict[str, Any]:
    """Get current IC factor weights from Redis."""
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(REDIS_KEY_IC_WEIGHTS)
        weights = json.loads(raw) if raw else {}
        history_result: list[dict[str, Any]] = []
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT factor_name, ic_score, computed_at
                            FROM factor_ic_history
                            ORDER BY computed_at DESC
                            LIMIT 20
                        """)
                    )
                    rows = result.all()
                    history_result = [
                        {
                            FieldName.FACTOR: row[0],
                            FieldName.IC_SCORE: float(row[1]),
                            FieldName.COMPUTED_AT: row[2].isoformat() if row[2] else None,
                        }
                        for row in rows
                    ]
            except Exception:
                pass
        return {
            FieldName.CURRENT_WEIGHTS: weights,
            FieldName.HISTORY: history_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "redis_cache" if is_db_available() else "in_memory",
        }
    except Exception:
        log_structured("error", "ic weights fetch failed", exc_info=True)
        return {
            FieldName.CURRENT_WEIGHTS: {},
            FieldName.HISTORY: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


@router.get("/learning/reflections")
async def get_reflections(limit: int = 20) -> dict[str, Any]:
    """Get recent reflection outputs from agent_logs."""
    if not is_db_available():
        reflections = _in_memory_reflections(limit=limit)
        return {
            FieldName.REFLECTIONS: reflections,
            FieldName.TOTAL: len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.REFLECTION, FieldName.LIMIT: limit},
            )
            rows = result.all()
        reflections = [
            {
                "trace_id": row[0],
                "summary": _as_dict(row[1]).get(FieldName.SUMMARY, ""),
                FieldName.HYPOTHESES: _as_dict(row[1]).get(FieldName.HYPOTHESES, []),
                FieldName.WINNING_FACTORS: _as_dict(row[1]).get(FieldName.WINNING_FACTORS, []),
                FieldName.LOSING_FACTORS: _as_dict(row[1]).get(FieldName.LOSING_FACTORS, []),
                FieldName.REGIME_EDGE: _as_dict(row[1]).get(FieldName.REGIME_EDGE, {}),
                FieldName.FILLS_ANALYZED: _as_dict(row[1]).get(FieldName.FILLS_ANALYZED),
                "timestamp": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
        return {
            FieldName.REFLECTIONS: reflections,
            FieldName.TOTAL: len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "reflections fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.patch("/learning/proposals/{trace_id}")
async def update_proposal_status(
    trace_id: str, status: str = Body(..., embed=True)
) -> dict[str, Any]:
    """Persist proposal approval or rejection back to agent_logs payload."""
    if status not in {ProposalStatus.APPROVED, ProposalStatus.REJECTED}:
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")
    if not is_db_available():
        if not _update_in_memory_proposal_status(trace_id, status):
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    UPDATE agent_logs
                    SET payload = (payload::jsonb || jsonb_build_object('status', :status::text))::text
                    WHERE trace_id = :trace_id AND log_type = :log_type
                    RETURNING trace_id
                """),
                {"trace_id": trace_id, "status": status, "log_type": LogType.PROPOSAL},
            )
            updated = result.fetchone()
            await session.commit()
        if updated is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal_status_update_failed", trace_id=trace_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/learning/loop")
async def get_learning_loop_state() -> dict[str, Any]:
    """Snapshot of the learning-loop control plane.

    Returns: latest grade, recent proposals (with applied_at if ProposalApplier
    has acted on them), per-symbol × signal-type loss attribution, and the
    current Redis control-plane state (trading_paused, signal_weight_scale,
    suspended agents). The frontend "Learning Loop" panel renders this.
    """
    out: dict[str, Any] = {
        FieldName.LATEST_GRADE: None,
        FieldName.RECENT_PROPOSALS: [],
        FieldName.LOSS_ATTRIBUTION: [],
        FieldName.CONTROL_PLANE: {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Control-plane Redis keys (best-effort — Redis must be reachable
    # but missing keys are not errors, they just mean "not set yet").
    try:
        redis_client = await get_redis()
        paused_raw = await redis_client.get(REDIS_KEY_TRADING_PAUSED)
        paused_reason = await redis_client.get(REDIS_KEY_TRADING_PAUSED_REASON)
        weight_scale_raw = await redis_client.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE)
        try:
            weight_scale = float(weight_scale_raw) if weight_scale_raw is not None else 1.0
        except (TypeError, ValueError):
            weight_scale = 1.0
        suspended: list[dict[str, Any]] = []
        for name in ALL_AGENT_NAMES:
            until_raw = await redis_client.get(REDIS_KEY_AGENT_SUSPENDED.format(name=name))
            if until_raw:
                try:
                    suspended.append({"agent_name": name, "suspended_until": float(until_raw)})
                except (TypeError, ValueError):
                    suspended.append({"agent_name": name, "suspended_until": None})
        out[FieldName.CONTROL_PLANE] = {
            FieldName.TRADING_PAUSED: paused_raw == "1",
            FieldName.TRADING_PAUSED_REASON: paused_reason,
            FieldName.SIGNAL_WEIGHT_SCALE: round(weight_scale, 6),
            FieldName.SUSPENDED_AGENTS: suspended,
        }
    except Exception:
        log_structured("warning", "learning_loop_control_plane_read_failed", exc_info=True)

    if not is_db_available():
        return out

    # 2. Latest grade — newest agent_logs row with log_type=LogType.GRADE.
    try:
        async with AsyncSessionFactory() as session:
            grade_row = await session.execute(
                text(
                    """
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"log_type": LogType.GRADE},
            )
            row = grade_row.first()
            if row is not None:
                payload = _as_dict(row[1])
                out[FieldName.LATEST_GRADE] = {
                    "trace_id": row[0],
                    "grade": payload.get(FieldName.GRADE),
                    "score_pct": payload.get(FieldName.SCORE_PCT),
                    "metrics": payload.get(FieldName.METRICS, {}),
                    FieldName.FILLS_GRADED: payload.get(FieldName.FILLS_GRADED),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
    except Exception:
        log_structured("warning", "learning_loop_latest_grade_failed", exc_info=True)

    # 3. Recent proposals with applied_at — ProposalApplier writes a
    # log_type=LogType.PROPOSAL row with FieldName.APPLIED_AT after each apply,
    # so a proposal is "pending" iff no log row exists with the same
    # trace_id and applied=true.
    try:
        async with AsyncSessionFactory() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT 20
                    """
                ),
                {"log_type": LogType.PROPOSAL},
            )
            proposals = []
            for row in rows.all():
                payload = _as_dict(row[1])
                proposals.append(
                    {
                        "trace_id": row[0],
                        "proposal_type": payload.get(FieldName.PROPOSAL_TYPE),
                        "action": payload.get(FieldName.ACTION),
                        "applied": bool(payload.get(FieldName.APPLIED, False)),
                        "applied_at": payload.get(FieldName.APPLIED_AT),
                        "applied_by": payload.get(FieldName.APPLIED_BY),
                        "message": payload.get(FieldName.MESSAGE),
                        "timestamp": row[2].isoformat() if row[2] else None,
                    }
                )
            out[FieldName.RECENT_PROPOSALS] = proposals
    except Exception:
        log_structured("warning", "learning_loop_proposals_failed", exc_info=True)

    # 4. Loss attribution — group closed trades by symbol × signal_type.
    # We pull the signal_type from agent_runs (joined by trace_id) so we
    # can show "every momentum_buy on BTC after threshold X loses".
    try:
        async with AsyncSessionFactory() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT
                        o.symbol AS symbol,
                        COALESCE(ar.signal_data::jsonb->>'signal_type', 'unknown') AS signal_type,
                        COUNT(*) AS trades,
                        COUNT(*) FILTER (WHERE COALESCE(tl.pnl, 0) < 0) AS losses,
                        COALESCE(SUM(tl.pnl), 0)::float AS total_pnl,
                        COALESCE(AVG(tl.pnl), 0)::float AS avg_pnl
                    FROM trade_lifecycle tl
                    JOIN orders o ON o.id::text = tl.order_id
                    LEFT JOIN agent_runs ar ON ar.trace_id = tl.execution_trace_id
                    WHERE tl.pnl IS NOT NULL
                    GROUP BY o.symbol, signal_type
                    ORDER BY total_pnl ASC
                    LIMIT 30
                    """
                )
            )
            attribution = []
            for row in rows.all():
                attribution.append(
                    {
                        "symbol": row[0],
                        "signal_type": row[1],
                        FieldName.TRADES: int(row[2] or 0),
                        FieldName.LOSSES: int(row[3] or 0),
                        FieldName.TOTAL_PNL: round(float(row[4] or 0.0), 2),
                        FieldName.AVG_PNL: round(float(row[5] or 0.0), 4),
                    }
                )
            out[FieldName.LOSS_ATTRIBUTION] = attribution
    except Exception:
        log_structured("warning", "learning_loop_loss_attribution_failed", exc_info=True)

    return out


# ---------------------------------------------------------------------------
# Trace view
# ---------------------------------------------------------------------------


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, Any]:
    """Return the full trace for a trace_id: agent_runs + agent_logs + agent_grades."""
    if not is_db_available():
        payload = _in_memory_trace_payload(trace_id)
        if (
            not payload[FieldName.AGENT_RUNS]
            and not payload[FieldName.AGENT_LOGS]
            and not payload[FieldName.AGENT_GRADES]
        ):
            raise HTTPException(status_code=404, detail="Trace not found") from None
        return payload

    try:
        async with AsyncSessionFactory() as session:
            run_result = await session.execute(
                text("""
                    SELECT id, source, run_type, status,
                           input_data, output_data, execution_time_ms, created_at
                    FROM agent_runs
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            runs = [
                {
                    FieldName.ID: str(r[0]),
                    "agent_name": r[1],
                    FieldName.RUN_TYPE: r[2],
                    "status": r[3],
                    "input_data": r[4],
                    "output_data": r[5],
                    "execution_time_ms": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in run_result.all()
            ]

            log_result = await session.execute(
                text("""
                    SELECT id, log_type, payload, created_at
                    FROM agent_logs
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            logs = [
                {
                    FieldName.ID: str(lg[0]),
                    "log_type": lg[1],
                    "payload": lg[2],
                    "created_at": lg[3].isoformat() if lg[3] else None,
                }
                for lg in log_result.all()
            ]

            grade_result = await session.execute(
                text("""
                    SELECT id, agent_id, grade_type, score, metrics, created_at
                    FROM agent_grades
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            grades = [
                {
                    FieldName.ID: str(g[0]),
                    "agent_id": str(g[1]),
                    "grade_type": g[2],
                    "score": float(g[3]) if g[3] is not None else None,
                    "metrics": g[4],
                    "created_at": g[5].isoformat() if g[5] else None,
                }
                for g in grade_result.all()
            ]

        if not runs and not logs and not grades:
            raise HTTPException(status_code=404, detail="Trace not found") from None

        return {
            "trace_id": trace_id,
            FieldName.AGENT_RUNS: runs,
            FieldName.AGENT_LOGS: logs,
            FieldName.AGENT_GRADES: grades,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "trace fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# Trade feed — end-to-end lifecycle per trade
# ---------------------------------------------------------------------------


def _normalize_in_memory_trade_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one in-memory trade row to the /trade-feed response contract.

    Returns ``None`` for malformed rows so the endpoint doesn't surface partial
    debug payloads as real trades.
    """
    trade_id = (
        raw.get(FieldName.ID)
        or raw.get(FieldName.EXECUTION_TRACE_ID)
        or raw.get(FieldName.ORDER_ID)
    )
    symbol = raw.get(FieldName.SYMBOL)
    side = raw.get(FieldName.SIDE)
    if not trade_id or not symbol or not side:
        return None

    def _as_iso(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        if isinstance(value, str):
            return value
        return str(value)

    return {
        FieldName.ID: str(trade_id),
        "symbol": str(symbol),
        "side": str(side),
        "qty": float(raw[FieldName.QTY]) if raw.get(FieldName.QTY) is not None else None,
        "entry_price": float(raw[FieldName.ENTRY_PRICE])
        if raw.get(FieldName.ENTRY_PRICE) is not None
        else None,
        "exit_price": float(raw[FieldName.EXIT_PRICE])
        if raw.get(FieldName.EXIT_PRICE) is not None
        else None,
        "pnl": float(raw[FieldName.PNL]) if raw.get(FieldName.PNL) is not None else None,
        "pnl_percent": float(raw[FieldName.PNL_PERCENT])
        if raw.get(FieldName.PNL_PERCENT) is not None
        else None,
        "order_id": str(raw[FieldName.ORDER_ID]) if raw.get(FieldName.ORDER_ID) else None,
        FieldName.EXECUTION_TRACE_ID: raw.get(FieldName.EXECUTION_TRACE_ID),
        FieldName.SIGNAL_TRACE_ID: raw.get(FieldName.SIGNAL_TRACE_ID),
        "grade": raw.get(FieldName.GRADE),
        "grade_score": float(raw[FieldName.GRADE_SCORE])
        if raw.get(FieldName.GRADE_SCORE) is not None
        else None,
        FieldName.GRADE_LABEL: raw.get(FieldName.GRADE_LABEL),
        "status": raw.get(FieldName.STATUS) or "filled",
        "filled_at": _as_iso(raw.get(FieldName.FILLED_AT)),
        FieldName.GRADED_AT: _as_iso(raw.get(FieldName.GRADED_AT)),
        FieldName.REFLECTED_AT: _as_iso(raw.get(FieldName.REFLECTED_AT)),
        "created_at": _as_iso(raw.get(FieldName.CREATED_AT)),
        FieldName.SESSION_ID: raw.get(FieldName.SESSION_ID),
    }


def _in_memory_trade_feed_payload(limit: int, session_id: str | None = None) -> dict[str, Any]:
    """Return normalized in-memory trade rows shaped to the trade-feed contract."""
    store = get_runtime_store()
    safe_limit = max(1, min(limit, 200))
    trades = [
        normalized
        for normalized in (
            _normalize_in_memory_trade_row(row) for row in reversed(store.trade_feed)
        )
        if normalized is not None
    ]
    if session_id:
        trades = [t for t in trades if str(t.get(FieldName.SESSION_ID) or "") == session_id]
    trades = trades[:safe_limit]
    return {
        FieldName.TRADES: trades,
        FieldName.COUNT: len(trades),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


@router.get("/trade-feed")
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, Any]:
    """Return the most recent trades with full lifecycle state.

    Each row shows what happened end-to-end: filled price, P&L, grade, and
    whether a reflection has been written.  The frontend displays these as a
    clear "Bought AAPL 100 @ $150 → +$23.50 (A)" feed.

    When ``count`` is 0 the response includes ``empty_reason`` to explain why:
    - ``db_degraded``            — DB unavailable; in-memory store also has no fills
    - ``no_orders_executed``     — DB reachable but orders table is empty
    - ``lifecycle_not_persisted``— orders exist but no trade_lifecycle rows yet
    - ``no_executable_intents``  — decisions were gated (HOLD/score/market) by EE
    """
    if not is_db_available():
        payload = _in_memory_trade_feed_payload(limit, session_id=session_id)
        if payload[FieldName.COUNT] == 0:
            payload[FieldName.EMPTY_REASON] = "db_degraded"
        return payload
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        tl.id, tl.symbol, tl.side, tl.qty, tl.entry_price, tl.exit_price,
                        tl.pnl, tl.pnl_percent, tl.order_id,
                        tl.execution_trace_id, tl.signal_trace_id,
                        tl.grade, tl.grade_score, tl.grade_label,
                        tl.status, tl.filled_at, tl.graded_at, tl.reflected_at,
                        tl.created_at,
                        COALESCE(o.strategy_id::text, tl.decision_trace_id) AS session_id
                    FROM trade_lifecycle tl
                    LEFT JOIN orders o ON o.id::text = tl.order_id::text
                    ORDER BY COALESCE(filled_at, created_at) ASC
                    LIMIT :limit
                """),
                {FieldName.LIMIT: min(limit, 200)},
            )
            rows = result.all()

        def _fmt(row: Any) -> dict[str, Any]:
            pnl = float(row[6]) if row[6] is not None else None
            pnl_pct = float(row[7]) if row[7] is not None else None
            return {
                FieldName.ID: str(row[0]),
                "symbol": row[1],
                "side": row[2],
                "qty": float(row[3]) if row[3] is not None else None,
                "entry_price": float(row[4]) if row[4] is not None else None,
                "exit_price": float(row[5]) if row[5] is not None else None,
                "pnl": round(pnl, 2) if pnl is not None else None,
                "pnl_percent": round(pnl_pct, 4) if pnl_pct is not None else None,
                "order_id": str(row[8]) if row[8] else None,
                FieldName.EXECUTION_TRACE_ID: row[9],
                FieldName.SIGNAL_TRACE_ID: row[10],
                "grade": row[11],
                "grade_score": float(row[12]) if row[12] is not None else None,
                FieldName.GRADE_LABEL: row[13],
                "status": row[14],
                "filled_at": row[15].isoformat() if row[15] else None,
                FieldName.GRADED_AT: row[16].isoformat() if row[16] else None,
                FieldName.REFLECTED_AT: row[17].isoformat() if row[17] else None,
                "created_at": row[18].isoformat() if row[18] else None,
                FieldName.SESSION_ID: row[19],
            }

        trades = [_fmt(r) for r in rows]
        if session_id:
            trades = [t for t in trades if str(t.get(FieldName.SESSION_ID) or "") == session_id]

        # Backward compatibility: if trade_lifecycle is empty, surface filled orders.
        if not trades:
            async with AsyncSessionFactory() as session:
                fallback_result = await session.execute(
                    text("""
                        SELECT
                            o.id,
                            o.symbol,
                            o.side,
                            COALESCE(NULLIF(to_jsonb(o)->>'filled_quantity', '')::numeric, o.qty),
                            o.price,
                            o.status,
                            to_jsonb(o)->>'trace_id',
                            o.created_at,
                            o.filled_at,
                            o.strategy_id::text AS session_id
                        FROM orders o
                        WHERE status IN ('filled', 'executed')
                        ORDER BY COALESCE(filled_at, created_at) DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: min(limit, 200)},
                )
                for row in fallback_result.all():
                    trades.append(
                        {
                            FieldName.ID: str(row[0]),
                            "symbol": row[1],
                            "side": row[2],
                            "qty": float(row[3]) if row[3] is not None else None,
                            "entry_price": float(row[4]) if row[4] is not None else None,
                            "exit_price": None,
                            "pnl": None,
                            "pnl_percent": None,
                            "order_id": str(row[0]),
                            FieldName.EXECUTION_TRACE_ID: row[6],
                            FieldName.SIGNAL_TRACE_ID: None,
                            "grade": None,
                            "grade_score": None,
                            FieldName.GRADE_LABEL: None,
                            "status": row[5],
                            "filled_at": row[8].isoformat() if row[8] else None,
                            FieldName.GRADED_AT: None,
                            FieldName.REFLECTED_AT: None,
                            "created_at": row[7].isoformat() if row[7] else None,
                            FieldName.SESSION_ID: row[9],
                        }
                    )
            if session_id:
                trades = [t for t in trades if str(t.get(FieldName.SESSION_ID) or "") == session_id]

        # DB returned zero rows — fall back to in-memory trade_feed so memory-
        # mode fills (paper trades that never reached trade_lifecycle because
        # the DB was down when they filled) still surface on the dashboard.
        if not trades:
            fallback = _in_memory_trade_feed_payload(limit, session_id=session_id)
            if fallback[FieldName.COUNT] > 0:
                return fallback

            # Diagnose why trade feed is empty so the UI can explain it.
            # Scope counts to the requested session when one is provided so the
            # reason reflects that session's state, not the global table state.
            empty_reason = "no_executable_intents"
            try:
                _diag_params: dict[str, Any] = {}
                if session_id:
                    _order_sql = "SELECT COUNT(*) FROM orders WHERE strategy_id::text = :sid"
                    # Mirror the COALESCE(o.strategy_id, tl.decision_trace_id) session
                    # mapping used by the main trade-feed query so the diagnostic
                    # counts lifecycle rows for this session regardless of which
                    # identifier was populated.
                    _lifecycle_sql = """
                        SELECT COUNT(*)
                        FROM trade_lifecycle tl
                        LEFT JOIN orders o ON o.id = tl.order_id
                        WHERE COALESCE(o.strategy_id::text, tl.decision_trace_id) = :sid
                    """
                    _diag_params = {FieldName.SID: session_id}
                else:
                    _order_sql = "SELECT COUNT(*) FROM orders"
                    _lifecycle_sql = "SELECT COUNT(*) FROM trade_lifecycle"
                async with AsyncSessionFactory() as diag_session:
                    order_count = (
                        await diag_session.execute(text(_order_sql), _diag_params)
                    ).scalar() or 0
                    lifecycle_count = (
                        await diag_session.execute(text(_lifecycle_sql), _diag_params)
                    ).scalar() or 0
                if order_count == 0:
                    empty_reason = "no_orders_executed"
                elif lifecycle_count == 0:
                    empty_reason = "lifecycle_not_persisted"
            except Exception:
                pass  # keep default reason

            # Fetch upstream pipeline counts so the UI can show the pipeline
            # is healthy even when no fills have occurred yet.
            upstream: dict[str, Any] = {
                FieldName.SIGNAL_EVENTS: 0,
                FieldName.DECISIONS_EVALUATED: 0,
                FieldName.EE_LAST_STATUS: None,
            }
            try:
                _redis = await get_redis()
                upstream[FieldName.SIGNAL_EVENTS] = await _redis.xlen(STREAM_SIGNALS)
                upstream[FieldName.DECISIONS_EVALUATED] = await _redis.xlen(STREAM_DECISIONS)
                _ee_raw = await _redis.get(REDIS_AGENT_STATUS_KEY.format(name=AGENT_EXECUTION))
                if _ee_raw:
                    _ee = json.loads(_ee_raw)
                    upstream[FieldName.EE_LAST_STATUS] = _ee.get(FieldName.LAST_EVENT, "")
                    upstream[FieldName.EE_EVENT_COUNT] = int(_ee.get(FieldName.EVENT_COUNT, 0))
            except Exception:
                pass

            return {
                FieldName.TRADES: [],
                FieldName.COUNT: 0,
                FieldName.EMPTY_REASON: empty_reason,
                FieldName.UPSTREAM_ACTIVITY: upstream,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return {
            FieldName.TRADES: trades,
            FieldName.COUNT: len(trades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "trade_feed_failed", exc_info=True)
        return _in_memory_trade_feed_payload(limit, session_id=session_id)


# ---------------------------------------------------------------------------
# Performance trends — agent grade history + P&L by day
# ---------------------------------------------------------------------------


def _performance_trends_from_runtime_store(source: str = "in_memory") -> dict[str, Any]:
    """Build a performance-trends payload from the runtime store (no DB needed)."""
    store = get_runtime_store()
    paired = store.paired_pnl_payload()
    summary_data = paired[FieldName.SUMMARY]
    orders = list(store.orders)
    total_trades = summary_data[FieldName.CLOSED_TRADES]
    wins = summary_data[FieldName.WINNING_TRADES]
    losses = total_trades - wins
    avg_win = 0.0
    avg_loss = 0.0
    if wins > 0:
        win_pnls = [
            float(o.get(FieldName.PNL) or 0.0)
            for o in orders
            if float(o.get(FieldName.PNL) or 0.0) > 0
        ]
        avg_win = round(sum(win_pnls) / wins, 2) if win_pnls else 0.0
    if losses > 0:
        loss_pnls = [
            float(o.get(FieldName.PNL) or 0.0)
            for o in orders
            if float(o.get(FieldName.PNL) or 0.0) < 0
        ]
        avg_loss = round(sum(loss_pnls) / losses, 2) if loss_pnls else 0.0
    return {
        "summary": {
            FieldName.TOTAL_PNL: summary_data[FieldName.TOTAL_PNL],
            FieldName.TOTAL_TRADES: total_trades,
            "win_rate": round(summary_data[FieldName.WIN_RATE_PERCENT] / 100.0, 4),
            FieldName.AVG_WIN: avg_win,
            FieldName.AVG_LOSS: avg_loss,
            FieldName.BEST_TRADE: round(
                max((float(o.get(FieldName.PNL) or 0.0) for o in orders), default=0.0), 2
            ),
            FieldName.WORST_TRADE: round(
                min((float(o.get(FieldName.PNL) or 0.0) for o in orders), default=0.0), 2
            ),
        },
        FieldName.DAILY_PNL: [],
        FieldName.GRADE_TREND: [],
        FieldName.EQUITY_CURVE: list(store.equity_curve[-200:]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        FieldName.HAS_DATA: bool(orders or store.open_positions()),
    }


@router.get("/performance-trends")
async def get_performance_trends() -> dict[str, Any]:
    """Return agent grade history and daily P&L for the last 30 days."""
    if not is_db_available():
        return _performance_trends_from_runtime_store()

    try:
        async with AsyncSessionFactory() as session:
            # Daily P&L from trade_lifecycle
            pnl_result = await session.execute(
                text("""
                    SELECT
                        DATE(filled_at AT TIME ZONE 'UTC') AS day,
                        SUM(pnl)                           AS daily_pnl,
                        COUNT(*)                           AS trade_count,
                        COUNT(*) FILTER (WHERE pnl > 0)    AS wins,
                        COUNT(*) FILTER (WHERE pnl <= 0)   AS losses,
                        AVG(pnl)                           AS avg_pnl
                    FROM trade_lifecycle
                    WHERE filled_at >= NOW() - INTERVAL '30 days'
                      AND status IN ('filled', 'graded', 'reflected')
                    GROUP BY day
                    ORDER BY day DESC
                """)
            )
            daily_pnl = [
                {
                    FieldName.DAY: str(r[0]),
                    "pnl": round(float(r[1]), 2) if r[1] is not None else 0.0,
                    FieldName.TRADE_COUNT: int(r[2]),
                    FieldName.WINS: int(r[3]),
                    FieldName.LOSSES: int(r[4]),
                    FieldName.AVG_PNL: round(float(r[5]), 2) if r[5] is not None else 0.0,
                }
                for r in pnl_result.all()
            ]

            # Grade distribution from agent_grades
            grade_result = await session.execute(
                text("""
                    SELECT
                        DATE(created_at AT TIME ZONE 'UTC') AS day,
                        AVG(score)                           AS avg_score_pct
                    FROM agent_grades
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY day
                    ORDER BY day DESC
                """)
            )
            grade_trend = [
                {
                    FieldName.DAY: str(r[0]),
                    FieldName.AVG_SCORE_PCT: round(float(r[1]), 1) if r[1] is not None else None,
                }
                for r in grade_result.all()
            ]

            # Summary stats
            summary_result = await session.execute(
                text("""
                    SELECT
                        COALESCE(SUM(pnl), 0)                       AS total_pnl,
                        COUNT(*)                                     AS total_trades,
                        COUNT(*) FILTER (WHERE pnl > 0)             AS total_wins,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0) AS avg_win,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl < 0), 0) AS avg_loss,
                        COALESCE(MAX(pnl), 0)                        AS best_trade,
                        COALESCE(MIN(pnl), 0)                        AS worst_trade
                    FROM trade_lifecycle
                    WHERE status IN ('filled', 'graded', 'reflected')
                """)
            )
            s = summary_result.first()
            total_trades = int(s[1]) if s else 0
            total_wins = int(s[2]) if s else 0
            summary = {
                FieldName.TOTAL_PNL: round(float(s[0]), 2) if s else 0.0,
                FieldName.TOTAL_TRADES: total_trades,
                "win_rate": round(total_wins / total_trades, 4) if total_trades else 0.0,
                FieldName.AVG_WIN: round(float(s[3]), 2) if s else 0.0,
                FieldName.AVG_LOSS: round(float(s[4]), 2) if s else 0.0,
                FieldName.BEST_TRADE: round(float(s[5]), 2) if s else 0.0,
                FieldName.WORST_TRADE: round(float(s[6]), 2) if s else 0.0,
            }

        return {
            "summary": summary,
            FieldName.DAILY_PNL: daily_pnl,
            FieldName.GRADE_TREND: grade_trend,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "performance_trends_failed", exc_info=True)
        return _performance_trends_from_runtime_store(source="db_error")


# ---------------------------------------------------------------------------
# Agent instances — lifecycle view
# ---------------------------------------------------------------------------


@router.get("/agent-instances")
async def get_agent_instances() -> dict[str, Any]:
    """Return all agent instances with lifecycle info.

    Active instances show how long they have been running and how many events
    they have processed.  Retired instances are kept for audit.
    """
    if not is_db_available():
        return _in_memory_agent_instances_payload()

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        id, instance_key, pool_name, status,
                        started_at, retired_at, event_count, metadata,
                        EXTRACT(EPOCH FROM (
                            COALESCE(retired_at, NOW()) - started_at
                        ))::int AS uptime_seconds
                    FROM agent_instances
                    ORDER BY started_at DESC
                    LIMIT 100
                """)
            )
            rows = result.all()

        instances = [
            {
                FieldName.ID: str(r[0]),
                FieldName.INSTANCE_KEY: r[1],
                FieldName.POOL_NAME: r[2],
                "status": r[3],
                FieldName.STARTED_AT: r[4].isoformat() if r[4] else None,
                FieldName.RETIRED_AT: r[5].isoformat() if r[5] else None,
                "event_count": int(r[6]) if r[6] is not None else 0,
                FieldName.UPTIME_SECONDS: int(r[8]) if r[8] is not None else 0,
            }
            for r in rows
        ]

        active = [i for i in instances if i[FieldName.STATUS] == "active"]
        retired = [i for i in instances if i[FieldName.STATUS] == "retired"]

        return {
            FieldName.INSTANCES: instances,
            FieldName.ACTIVE_COUNT: len(active),
            FieldName.RETIRED_COUNT: len(retired),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "agent_instances_failed", exc_info=True)
        return {
            FieldName.INSTANCES: [],
            FieldName.ACTIVE_COUNT: 0,
            FieldName.RETIRED_COUNT: 0,
            "error": "agent_instances_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Challenger agent management
# ---------------------------------------------------------------------------


@router.post("/challengers/spawn")
async def spawn_challenger(
    request: Request,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Spawn a new ChallengerAgent from an approved new_agent proposal.

    Body: { "challenger_config": {...}, "max_fills": 200 }

    The challenger runs in parallel with the existing pipeline agents,
    tracks its own grades, and retires itself after max_fills events,
    publishing a summary to the proposals stream.
    """
    try:
        event_bus = getattr(request.app.state, "event_bus", None)
        dlq_manager = getattr(request.app.state, "dlq_manager", None)
        agents: list[Any] = getattr(request.app.state, "agents", [])

        if event_bus is None or dlq_manager is None:
            raise HTTPException(status_code=503, detail="Event bus not ready") from None

        challenger_config = body.get(FieldName.CHALLENGER_CONFIG, {})
        max_fills = int(body.get(FieldName.MAX_FILLS, ChallengerAgent.DEFAULT_MAX_FILLS))

        challenger = ChallengerAgent(
            event_bus,
            dlq_manager,
            challenger_config=challenger_config,
            max_fills=max_fills,
        )
        await challenger.start()
        agents.append(challenger)

        log_structured(
            "info",
            "challenger_spawned",
            challenger_id=challenger._challenger_id,
            instance_id=challenger._instance_id,
            max_fills=max_fills,
        )
        return {
            FieldName.CHALLENGER_ID: challenger._challenger_id,
            FieldName.INSTANCE_ID: challenger._instance_id,
            FieldName.CONSUMER: challenger.consumer,
            FieldName.MAX_FILLS: max_fills,
            "status": "spawned",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "challenger_spawn_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/challengers")
async def list_challengers(request: Request) -> dict[str, Any]:
    """List all active challenger agent instances."""
    try:
        agents: list[Any] = getattr(request.app.state, "agents", [])
        challengers = [a for a in agents if isinstance(a, ChallengerAgent)]

        return {
            FieldName.CHALLENGERS: [
                {
                    FieldName.CHALLENGER_ID: c._challenger_id,
                    FieldName.INSTANCE_ID: c._instance_id,
                    FieldName.CONSUMER: c.consumer,
                    FieldName.FILLS: c._fills,
                    FieldName.MAX_FILLS: c._max_fills,
                    FieldName.CONFIG: c._config,
                    FieldName.RUNNING: c._running,
                }
                for c in challengers
            ],
            FieldName.COUNT: len(challengers),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "challengers_list_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/kill-switch")
async def get_kill_switch() -> dict[str, Any]:
    """Get current kill switch state."""
    try:
        redis_client = await get_redis()
        value = await redis_client.get(REDIS_KEY_KILL_SWITCH)
        updated_at = await redis_client.get(REDIS_KEY_KILL_SWITCH_UPDATED_AT)
        return {
            FieldName.ACTIVE: value == "1",
            "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "kill_switch_read_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("/kill-switch")
async def toggle_kill_switch(active: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Toggle the trading kill switch."""
    try:
        redis_client = await get_redis()

        # Store kill switch state in Redis
        await redis_client.set(REDIS_KEY_KILL_SWITCH, "1" if active else "0")
        await redis_client.set(
            REDIS_KEY_KILL_SWITCH_UPDATED_AT, datetime.now(timezone.utc).isoformat()
        )

        # Log the action
        log_structured(
            "info",
            "kill_switch_toggled",
            active=active,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        return {
            FieldName.ACTIVE: active,
            "message": f"Kill switch {'activated' if active else 'deactivated'}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "kill switch toggle failed", active=active, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/debug/state")
async def get_dashboard_debug_state() -> dict[str, Any]:
    """Debug snapshot from in-memory runtime store only.

    This endpoint is intentionally memory-scoped so operators can inspect
    fallback/runtime state. It does not query Postgres and must not claim the
    payload is DB-sourced when db_available=True.
    """
    store = get_runtime_store()
    diagnostics = await hydrate_dashboard_state_from_redis()
    snapshot = store.dashboard_fallback_snapshot()
    paired = store.paired_pnl_payload()
    paired_closed_trades = paired.get(FieldName.CLOSED_TRADES, [])
    paired_summary = paired.get(FieldName.SUMMARY, {})
    summary_closed_trades = int(paired_summary.get(FieldName.CLOSED_TRADES, 0) or 0)
    db_available = is_db_available()
    equity_curve = snapshot.get(FieldName.EQUITY_CURVE, [])
    open_positions_list = snapshot.get(FieldName.POSITIONS, [])
    decisions_list = snapshot.get(FieldName.DECISIONS, [])
    notifications_list = snapshot.get(FieldName.NOTIFICATIONS, [])
    has_data = bool(decisions_list or open_positions_list or snapshot.get(FieldName.ORDERS))
    return {
        FieldName.DB_AVAILABLE: db_available,
        FieldName.SOURCE: diagnostics[FieldName.SOURCE],
        FieldName.HAS_DATA: has_data,
        FieldName.LAST_ERROR: diagnostics[FieldName.LAST_ERROR],
        FieldName.LEDGER_SOURCE: diagnostics[FieldName.LEDGER_SOURCE],
        FieldName.PERSISTENCE_SOURCE: diagnostics[FieldName.PERSISTENCE_SOURCE],
        FieldName.SCOPE: "runtime_store",
        FieldName.RUNTIME_STORE: {
            FieldName.DECISIONS_COUNT: len(decisions_list),
            FieldName.NOTIFICATIONS_COUNT: len(notifications_list),
            FieldName.OPEN_POSITIONS: len(open_positions_list),
            FieldName.CLOSED_TRADES: summary_closed_trades,
            FieldName.EQUITY_POINTS: len(equity_curve),
        },
        "pnl": {
            FieldName.TOTAL_PNL: paired_summary.get(FieldName.TOTAL_PNL, 0.0),
            FieldName.REALIZED_PNL: paired_summary.get(FieldName.REALIZED_PNL, 0.0),
            "unrealized_pnl": paired_summary.get(FieldName.UNREALIZED_PNL, 0.0),
            "win_rate": round(paired_summary.get(FieldName.WIN_RATE_PERCENT, 0.0) / 100.0, 4),
            FieldName.ACTIVE_POSITIONS: paired_summary.get(FieldName.OPEN_POSITIONS, 0),
            FieldName.EQUITY_CURVE_POINTS: len(equity_curve),
        },
        FieldName.COUNTS: {
            FieldName.REDIS_HYDRATION_STATUS: diagnostics[FieldName.HYDRATION_STATUS],
            FieldName.REDIS_DECISIONS_SEEN: diagnostics[FieldName.REDIS_DECISIONS_SEEN],
            FieldName.REDIS_DECISIONS_APPLIED: diagnostics[FieldName.REDIS_DECISIONS_APPLIED],
            FieldName.REDIS_NOTIFICATIONS_SEEN: diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN],
            FieldName.REDIS_NOTIFICATIONS_APPLIED: diagnostics[
                FieldName.REDIS_NOTIFICATIONS_APPLIED
            ],
            FieldName.APPLIED_DECISION_KEYS: diagnostics[FieldName.APPLIED_DECISION_KEYS],
            FieldName.DECISIONS: len(decisions_list),
            FieldName.NOTIFICATIONS: len(notifications_list),
            FieldName.OPEN_POSITIONS: len(open_positions_list),
            FieldName.CLOSED_TRADES: summary_closed_trades,
            FieldName.EQUITY_POINTS: len(equity_curve),
        },
        FieldName.LATEST_DECISION: (decisions_list or [None])[0],
        FieldName.LATEST_NOTIFICATION: (notifications_list or [None])[0],
        FieldName.LATEST_OPEN_POSITION: (open_positions_list or [None])[0],
        FieldName.LATEST_CLOSED_TRADE: (paired_closed_trades or [None])[-1],
        "summary": paired_summary,
    }
