"""
Observability API - System status and real-time logs.

Aggregates stream lag, agent pulse, and database health.
Provides SSE streaming of agent logs.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import redis.asyncio as redis
from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.constants import REDIS_KEY_KILL_SWITCH, REDIS_KEY_TRADING_PAUSED, FieldName
from api.events.bus import DEFAULT_GROUP
from api.runtime_state import is_db_available
from api.services.agent_log_stream import (
    agent_log_stream_response,
    memory_mode_log_stream_response,
)
from api.utils import now_iso

from ..config import get_database_url
from ..core.models import Order, SystemMetrics
from ..observability import log_structured
from ..redis_client import get_redis

router = APIRouter(prefix="/system", tags=["system"])

# Database connection — built lazily so import succeeds when DATABASE_URL is None
_engine = None
_session_factory = None


def _get_session_factory():
    global _engine, _session_factory
    if _session_factory is None:
        url = get_database_url()
        _engine = create_async_engine(url, pool_size=10, max_overflow=20)
        _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


# Legacy alias used by get_system_status below
def _make_session():
    return _get_session_factory()()


@router.get("/trading-mode")
async def get_trading_mode() -> dict[str, Any]:
    """Simple Redis-backed trading status — works without DB.

    Returns "PAUSED" when the learning-loop circuit breaker is active or
    the kill switch is set, "TRADING" otherwise.
    """
    try:
        redis_client = await get_redis()
        kill_switch = await redis_client.get(REDIS_KEY_KILL_SWITCH)
        trading_paused = await redis_client.get(REDIS_KEY_TRADING_PAUSED)
        if kill_switch == "1":
            status = "KILL_SWITCH"
        elif trading_paused == "1":
            status = "PAUSED"
        else:
            status = "TRADING"
        return {
            "status": status,
            FieldName.KILL_SWITCH_ACTIVE: kill_switch == "1",
            FieldName.CIRCUIT_BREAKER_ACTIVE: trading_paused == "1",
        }
    except Exception:
        log_structured("warning", "system_trading_mode_check_failed", exc_info=True)
        return {
            "status": "UNKNOWN",
            FieldName.KILL_SWITCH_ACTIVE: None,
            FieldName.CIRCUIT_BREAKER_ACTIVE: None,
            "error": "redis_unavailable",
        }


@router.post("/trading-mode")
async def set_trading_mode(body: Annotated[dict[str, Any], Body()] = None) -> dict[str, Any]:
    """Pause or resume trading via the learning-loop circuit breaker key.

    POST body: {"status": "TRADING"} to resume, {"status": "PAUSED"} to pause.
    """
    if body is None:
        body = {}
    status = str(body.get(FieldName.STATUS, "TRADING")).strip().upper()
    if status not in ("TRADING", "PAUSED"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status {status!r}. Use 'TRADING' or 'PAUSED'.",
        )
    try:
        redis_client = await get_redis()
        if status == "TRADING":
            await redis_client.delete(REDIS_KEY_TRADING_PAUSED)
            log_structured("info", "system_trading_mode_resumed_via_api")
        else:
            await redis_client.set(REDIS_KEY_TRADING_PAUSED, "1")
            log_structured("info", "system_trading_mode_paused_via_api")
        # Report the actual effective status — kill switch takes precedence over the
        # learning-loop pause key, so a "resume" request must not claim trading is
        # active when the manual kill switch is still engaged.
        kill_switch = await redis_client.get(REDIS_KEY_KILL_SWITCH)
        effective_status = "KILL_SWITCH" if kill_switch == "1" else status
        return {"status": effective_status, FieldName.OK: True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/status")
async def get_system_status():
    """Aggregate system status including stream lag, agent pulse, and database health."""
    if not is_db_available():
        stream_lag = await get_stream_lag()
        return {
            "timestamp": now_iso(),
            FieldName.MODE: "memory",
            FieldName.AGENT_PULSE: [],
            FieldName.DATABASE_HEALTH: {
                FieldName.PENDING_ORDERS_LAST_HOUR: 0,
                FieldName.FILLED_ORDERS_LAST_HOUR: 0,
                FieldName.TOTAL_ORDERS_LAST_HOUR: 0,
            },
            FieldName.STREAM_LAG: stream_lag,
        }

    async with _make_session() as session:
        # Agent Pulse - schema compatible for legacy/new agent_logs layouts
        col_result = await session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'agent_logs'
                """
            )
        )
        available_columns = {row[0] for row in col_result}
        time_col = "created_at" if "created_at" in available_columns else "timestamp"
        run_col = "agent_run_id" if "agent_run_id" in available_columns else "source"
        level_col = "log_level" if "log_level" in available_columns else "log_type"

        agent_result = await session.execute(
            text(
                f"""
                SELECT
                    {run_col} AS agent_run_id,
                    MAX({time_col}) AS last_seen,
                    MAX({level_col}) AS last_level
                FROM agent_logs
                GROUP BY {run_col}
                ORDER BY MAX({time_col}) DESC
                LIMIT 8
                """
            )
        )
        agent_pulse = [
            {
                "agent_id": row.agent_run_id,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                FieldName.LAST_LEVEL: row.last_level,
            }
            for row in agent_result
        ]

        # Database Health - orders in last hour
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

        order_stats_query = (
            select(Order.status, func.count(Order.id).label("count"))
            .where(Order.created_at >= hour_ago)
            .group_by(Order.status)
        )

        order_result = await session.execute(order_stats_query)
        order_stats = {row.status: row.count for row in order_result}

        pending_orders = order_stats.get(FieldName.PENDING, 0)
        filled_orders = order_stats.get(FieldName.FILLED, 0)

        # Stream Lag calculation
        stream_lag = await get_stream_lag()

        # Sanitize lag values to prevent NaN
        sanitized_lag = {}
        for stream, data in stream_lag.items():
            if isinstance(data, dict):
                sanitized_lag[stream] = {
                    FieldName.LAG_MS: data.get(FieldName.LAG_MS, 0) or 0,
                    FieldName.LAG_SECONDS: data.get(FieldName.LAG_SECONDS, 0) or 0,
                    FieldName.HEAD_ID: data.get(FieldName.HEAD_ID, ""),
                    FieldName.LAST_PROCESSED_ID: data.get(FieldName.LAST_PROCESSED_ID, ""),
                    "error": data.get(FieldName.ERROR),
                }
            else:
                sanitized_lag[stream] = data

        return {
            "timestamp": now_iso(),
            FieldName.AGENT_PULSE: agent_pulse,
            FieldName.DATABASE_HEALTH: {
                FieldName.PENDING_ORDERS_LAST_HOUR: pending_orders,
                FieldName.FILLED_ORDERS_LAST_HOUR: filled_orders,
                FieldName.TOTAL_ORDERS_LAST_HOUR: pending_orders + filled_orders,
            },
            FieldName.STREAM_LAG: sanitized_lag,
        }


async def get_stream_lag() -> dict[str, Any]:
    """Calculate stream lag by comparing Redis head ID to last processed ID."""
    try:
        redis_client = await get_redis()

        streams = ["orders", "executions", "agent_logs", "system_metrics"]
        lag_info = {}

        for stream in streams:
            try:
                # Get stream info (head ID)
                info = await redis_client.xinfo_stream(stream)
                head_id = info.get("last-generated-id", "0-0")

                # Get last processed ID from consumer group
                try:
                    groups = await redis_client.xinfo_groups(stream)
                    for group in groups:
                        if group.get(FieldName.NAME) == DEFAULT_GROUP:
                            last_delivered = group.get("last-delivered-id", "0-0")
                            # Calculate lag (simplified - just comparing timestamps)
                            head_timestamp = int(head_id.split("-")[0])
                            last_timestamp = int(last_delivered.split("-")[0])
                            lag_ms = head_timestamp - last_timestamp

                            lag_info[stream] = {
                                FieldName.HEAD_ID: head_id,
                                FieldName.LAST_PROCESSED_ID: last_delivered,
                                FieldName.LAG_MS: lag_ms,
                                FieldName.LAG_SECONDS: lag_ms / 1000,
                            }
                            break
                    else:
                        lag_info[stream] = {"error": "Consumer group not found"}
                except redis.ResponseError:
                    lag_info[stream] = {"error": "No consumer group"}

            except redis.ResponseError as e:
                lag_info[stream] = {"error": str(e)}

        return lag_info

    except Exception as e:
        log_structured("error", "stream lag calculation failed", exc_info=True)
        return {"error": str(e)}


@router.get("/logs")
async def stream_agent_logs(
    agent_id: str = Query(None, description="Filter by agent ID"),
    level: str = Query(None, description="Filter by log level"),
    limit: int = Query(100, description="Maximum number of recent logs to stream"),
):
    """Stream agent logs using Server-Sent Events."""
    if not is_db_available():
        return memory_mode_log_stream_response()
    return agent_log_stream_response(
        _make_session,
        limit=limit,
        agent_id=agent_id,
        level=level,
        ts_field=FieldName.TIMESTAMP,
        include_trace_id=False,
    )


@router.get("/metrics")
async def get_system_metrics(
    metric_name: str = Query(None, description="Filter by metric name"),
    hours: int = Query(1, description="Hours of history to fetch"),
):
    """Get system metrics for monitoring."""
    if not is_db_available():
        return {"metrics": [], FieldName.COUNT: 0, FieldName.MODE: "memory"}

    async with _make_session() as session:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        query = select(SystemMetrics).where(SystemMetrics.timestamp >= since)

        if metric_name:
            query = query.where(SystemMetrics.metric_name == metric_name)

        query = query.order_by(SystemMetrics.timestamp.desc()).limit(1000)

        result = await session.execute(query)
        metrics = result.scalars().all()

        return {
            "metrics": [
                {
                    FieldName.METRIC_NAME: m.metric_name,
                    FieldName.METRIC_VALUE: float(m.metric_value or 0),  # Guard against NaN/None
                    FieldName.METRIC_UNIT: m.metric_unit,
                    FieldName.TAGS: m.tags or {},  # Guard against None
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in metrics
            ],
            FieldName.COUNT: len(metrics),
        }


@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    try:
        # Test database connection
        async with _make_session() as session:
            await session.execute(text("SELECT 1"))

        # Test Redis connection
        redis_client = await get_redis()
        await redis_client.ping()

        return {
            "status": "healthy",
            "timestamp": now_iso(),
            FieldName.DATABASE: "connected",
            FieldName.REDIS: "connected",
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": now_iso(),
            "error": str(e),
        }
