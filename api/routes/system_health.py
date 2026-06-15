"""
System Health Dashboard - Real-time monitoring of 8-agent trading loop.

Traffic light system with pulse monitoring, stream lag, and integrity checks.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.constants import ALL_AGENT_NAMES, REDIS_AGENT_STATUS_KEY, FieldName
from api.runtime_state import is_db_available
from api.services.agent_log_stream import (
    agent_log_stream_response,
    memory_mode_log_stream_response,
)
from api.utils import now_iso

from ..config import get_database_url
from ..core.models import Event, Order, Position
from ..observability import log_structured
from ..redis_client import get_redis

router = APIRouter(prefix="/health", tags=["system-health"])

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


def _make_session():
    return _get_session_factory()()


# ============================================================================
# BACKEND HEALTH APIS
# ============================================================================


@router.get("/pulse")
async def get_system_pulse():
    """Real-time system pulse with traffic light status."""
    try:
        # Redis connection
        redis_client = await get_redis()

        # Get stream health metrics
        stream_health = await get_stream_health(redis_client)

        # Get worker heartbeats
        heartbeats = await get_worker_heartbeats(redis_client)

        # Get DLQ count
        dlq_count = await redis_client.xlen("dead_letter_stream")

        # Get DB pool status (simplified)
        db_pool_status = await get_db_pool_status()

        # Calculate traffic light status
        traffic_light = calculate_traffic_light(stream_health, dlq_count, db_pool_status)

        return {
            "timestamp": now_iso(),
            FieldName.TRAFFIC_LIGHT: traffic_light,
            FieldName.STREAM_HEALTH: stream_health,
            FieldName.WORKER_HEARTBEATS: heartbeats,
            FieldName.DLQ_COUNT: dlq_count,
            FieldName.DB_POOL_STATUS: db_pool_status,
        }

    except Exception as e:
        log_structured("error", "pulse api error", exc_info=True)
        return {
            "timestamp": now_iso(),
            FieldName.TRAFFIC_LIGHT: "red",
            "error": str(e),
        }


@router.get("/idempotency")
async def get_idempotency_audit():
    """Audit idempotency by comparing processed_events vs orders."""
    try:
        async with _make_session() as session:
            # Count processed events in last hour
            hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

            processed_query = select(func.count(Event.id)).where(
                Event.created_at >= hour_ago,
                Event.event_type.in_(["order.created", "order.filled"]),
            )
            processed_count = await session.scalar(processed_query)

            # Count orders in last hour
            orders_query = select(func.count(Order.id)).where(Order.created_at >= hour_ago)
            orders_count = await session.scalar(orders_query)

            # Calculate ratio
            ratio = processed_count / orders_count if orders_count > 0 else 0

            return {
                "timestamp": now_iso(),
                FieldName.PROCESSED_EVENTS_LAST_HOUR: processed_count,
                FieldName.ORDERS_LAST_HOUR: orders_count,
                FieldName.RATIO: round(ratio, 3),
                "status": "healthy" if 0.8 <= ratio <= 1.2 else "warning",
            }

    except Exception as e:
        log_structured("error", "idempotency audit error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/position-sync")
async def get_position_sync_status():
    """Check position sync status - highlight mismatches."""
    try:
        async with _make_session() as session:
            # Get recent fills that should have updated positions
            hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

            fills_query = (
                select(Event)
                .where(Event.event_type == "order.filled", Event.created_at >= hour_ago)
                .order_by(Event.created_at.desc())
                .limit(50)
            )

            fills = await session.execute(fills_query)
            fill_events = fills.scalars().all()

            # Check corresponding positions
            sync_status = []
            for fill in fill_events:
                fill_data = fill.data
                strategy_id = fill_data.get(FieldName.STRATEGY_ID)
                symbol = fill_data.get(FieldName.SYMBOL)

                if strategy_id and symbol:
                    position_query = select(Position).where(
                        Position.strategy_id == strategy_id, Position.symbol == symbol
                    )
                    position = await session.scalar(position_query)

                    sync_status.append(
                        {
                            FieldName.FILL_ID: fill.id,
                            "strategy_id": strategy_id,
                            "symbol": symbol,
                            FieldName.FILL_TIME: fill.created_at.isoformat(),
                            FieldName.POSITION_EXISTS: position is not None,
                            FieldName.POSITION_QUANTITY: (
                                float(position.quantity) if position else None
                            ),
                            FieldName.EXPECTED_QUANTITY: fill_data.get(FieldName.NEW_QUANTITY),
                            FieldName.SYNC_STATUS: "synced" if position else "missing",
                            FieldName.ALERT_LEVEL: "red" if not position else "green",
                        }
                    )

            return {
                "timestamp": now_iso(),
                FieldName.TOTAL_FILLS: len(fill_events),
                FieldName.SYNCED_COUNT: len(
                    [s for s in sync_status if s[FieldName.SYNC_STATUS] == "synced"]
                ),
                FieldName.SYNC_STATUS: sync_status,
            }

    except Exception as e:
        log_structured("error", "position sync error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/logs")
async def stream_agent_logs(
    limit: int = Query(50, description="Number of recent logs"),
    agent_id: str = Query(None, description="Filter by agent ID"),
    level: str = Query(None, description="Filter by log level"),
):
    """Stream agent logs with msg_id and trace_id for cross-reference."""
    if not is_db_available():
        return memory_mode_log_stream_response()
    return agent_log_stream_response(
        _make_session,
        limit=limit,
        agent_id=agent_id,
        level=level,
        ts_field=FieldName.CREATED_AT,
        include_trace_id=True,
    )


@router.post("/pause")
async def pause_consumers():
    """Kill switch - pause all consumers."""
    try:
        redis_client = await get_redis()

        # Send pause signal to all workers
        await redis_client.publish("consumer:control", json.dumps({"action": "pause"}))

        return {
            "timestamp": now_iso(),
            "status": "pause_signal_sent",
            "message": "Pause signal sent to all consumers",
        }

    except Exception as e:
        log_structured("error", "pause command error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/resume")
async def resume_consumers():
    """Resume all consumers."""
    try:
        redis_client = await get_redis()

        # Send resume signal to all workers
        await redis_client.publish("consumer:control", json.dumps({"action": "resume"}))

        return {
            "timestamp": now_iso(),
            "status": "resume_signal_sent",
            "message": "Resume signal sent to all consumers",
        }

    except Exception as e:
        log_structured("error", "resume command error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def get_stream_health(redis_client) -> dict[str, Any]:
    """Get comprehensive stream health metrics."""
    streams = [
        "orders",
        "executions",
        "agent_logs",
        "system_metrics",
        "trade_performance",
    ]
    health = {}

    for stream in streams:
        try:
            # Get stream info
            info = await redis_client.xinfo_stream(stream)
            total_backlog = info.get(FieldName.LENGTH, 0)

            # Get pending info
            try:
                pending = await redis_client.xpending_range(
                    stream, "trading_workers", "-", "+", 1000
                )
                pending_ack = len(pending)

                # Find oldest pending message
                oldest_age = 0
                if pending:
                    oldest_timestamp = int(pending[0][1])  # First entry's idle time
                    oldest_age = oldest_timestamp / 1000  # Convert to seconds
            except redis.ResponseError:
                pending_ack = 0
                oldest_age = 0

            health[stream] = {
                "status": "healthy",
                FieldName.BACKLOG: total_backlog,
                FieldName.PENDING: pending_ack,
                FieldName.OLDEST_PENDING_AGE_SECONDS: oldest_age,
                FieldName.LAST_CHECKED: now_iso(),
            }

        except Exception as e:
            # Handle missing streams gracefully
            health[stream] = {
                "status": "missing",
                FieldName.BACKLOG: 0,
                FieldName.PENDING: 0,
                FieldName.OLDEST_PENDING_AGE_SECONDS: 0,
                "error": str(e),
                FieldName.LAST_CHECKED: now_iso(),
            }

    return health


async def get_worker_heartbeats(redis_client) -> dict[str, Any]:
    """Get worker heartbeat status."""
    # Heartbeats are written as individual string keys by write_heartbeat()
    # (REDIS_AGENT_STATUS_KEY = "agent:status:{name}"), NOT as a Redis hash.
    # The former hgetall("agent:heartbeats") always returned {} because that
    # hash key is never written.
    try:
        heartbeats: dict[str, Any] = {}
        for agent_name in ALL_AGENT_NAMES:
            key = REDIS_AGENT_STATUS_KEY.format(name=agent_name)
            raw = await redis_client.get(key)
            if raw is None:
                continue
            try:
                parsed = json.loads(raw)
                last_seen_str = parsed.get(FieldName.LAST_SEEN_AT)
                if last_seen_str:
                    last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                    age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
                else:
                    age_seconds = None
                heartbeats[agent_name] = {
                    **parsed,
                    FieldName.AGE_SECONDS: age_seconds,
                    "status": "alive"
                    if (age_seconds is not None and age_seconds < 120)
                    else "missing",
                }
            except (json.JSONDecodeError, ValueError):
                heartbeats[agent_name] = {"status": "invalid", FieldName.RAW_DATA: raw}
        return heartbeats

    except Exception as e:
        return {"error": str(e)}


async def get_db_pool_status() -> dict[str, Any]:
    """Get simplified DB pool status."""
    try:
        async with _make_session() as session:
            # Simple health check
            await session.execute(text("SELECT 1"))

            # In a real implementation, you'd get actual pool metrics
            # For now, return simulated status
            return {
                FieldName.ACTIVE_CONNECTIONS: 15,  # Would come from engine.pool.status()
                FieldName.IDLE_CONNECTIONS: 35,
                FieldName.TOTAL_CONNECTIONS: 50,
                FieldName.POOL_UTILIZATION_PERCENT: 30,
                "status": "healthy",
            }

    except Exception as e:
        return {"status": "error", "error": str(e)}


def calculate_traffic_light(stream_health: dict, dlq_count: int, db_pool_status: dict) -> str:
    """Calculate traffic light status."""
    # Check for critical conditions
    if db_pool_status.get(FieldName.STATUS) == "error":
        return "red"

    if dlq_count > 0:
        return "yellow"

    # Check stream health
    for _stream, health in stream_health.items():
        if health.get(FieldName.STATUS) == "error":
            return "red"
        if health.get(FieldName.OLDEST_PENDING_AGE_SECONDS, 0) > 60:
            return "yellow"
        if health.get(FieldName.PENDING, 0) > 100:
            return "yellow"

    # Check DB pool utilization
    if db_pool_status.get(FieldName.POOL_UTILIZATION_PERCENT, 0) > 80:
        return "yellow"

    return "green"
