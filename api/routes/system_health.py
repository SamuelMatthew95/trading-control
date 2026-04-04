"""
System Health Dashboard - Real-time monitoring of 8-agent trading loop.

Traffic light system with pulse monitoring, stream lag, and integrity checks.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings
from ..core.models import Event, Order, Position
from ..observability import log_structured

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["system-health"])

settings = get_settings()

# Database connection
database_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(database_url, pool_size=10, max_overflow=20)
session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ============================================================================
# BACKEND HEALTH APIS
# ============================================================================


@router.get("/pulse")
async def get_system_pulse():
    """Real-time system pulse with traffic light status."""
    try:
        # Redis connection
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )

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

        await redis_client.close()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "traffic_light": traffic_light,
            "stream_health": stream_health,
            "worker_heartbeats": heartbeats,
            "dlq_count": dlq_count,
            "db_pool_status": db_pool_status,
        }

    except Exception as e:
        log_structured("error", "pulse api error", error=str(e))
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "traffic_light": "red",
            "error": str(e),
        }


@router.get("/idempotency")
async def get_idempotency_audit():
    """Audit idempotency by comparing processed_events vs orders."""
    try:
        async with session_factory() as session:
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "processed_events_last_hour": processed_count,
                "orders_last_hour": orders_count,
                "ratio": round(ratio, 3),
                "status": "healthy" if 0.8 <= ratio <= 1.2 else "warning",
            }

    except Exception as e:
        log_structured("error", "idempotency audit error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/position-sync")
async def get_position_sync_status():
    """Check position sync status - highlight mismatches."""
    try:
        async with session_factory() as session:
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
                strategy_id = fill_data.get("strategy_id")
                symbol = fill_data.get("symbol")

                if strategy_id and symbol:
                    position_query = select(Position).where(
                        Position.strategy_id == strategy_id, Position.symbol == symbol
                    )
                    position = await session.scalar(position_query)

                    sync_status.append(
                        {
                            "fill_id": fill.id,
                            "strategy_id": strategy_id,
                            "symbol": symbol,
                            "fill_time": fill.created_at.isoformat(),
                            "position_exists": position is not None,
                            "position_quantity": (float(position.quantity) if position else None),
                            "expected_quantity": fill_data.get("new_quantity"),
                            "sync_status": "synced" if position else "missing",
                            "alert_level": "red" if not position else "green",
                        }
                    )

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_fills": len(fill_events),
                "synced_count": len([s for s in sync_status if s["sync_status"] == "synced"]),
                "sync_status": sync_status,
            }

    except Exception as e:
        log_structured("error", "position sync error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/logs")
async def stream_agent_logs(
    limit: int = Query(50, description="Number of recent logs"),
    agent_id: str = Query(None, description="Filter by agent ID"),
    level: str = Query(None, description="Filter by log level"),
):
    """Stream agent logs with msg_id and trace_id for cross-reference."""

    async def log_generator():
        try:
            async with session_factory() as session:
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
                trace_col = "trace_id" if "trace_id" in available_columns else "NULL"
                step_name_col = "step_name" if "step_name" in available_columns else "NULL"
                step_data_col = "step_data" if "step_data" in available_columns else "NULL"
                payload_message = (
                    "payload->>'message'" if "payload" in available_columns else "NULL"
                )
                payload_content = (
                    "payload->>'content'" if "payload" in available_columns else "NULL"
                )
                legacy_log_type = "log_type" if "log_type" in available_columns else "NULL"
                message_col = "message" if "message" in available_columns else "NULL"

                base_sql = f"""
                    SELECT
                        id,
                        {trace_col} AS trace_id,
                        {run_col} AS agent_run_id,
                        {level_col} AS log_level,
                        COALESCE({message_col}, {payload_message}, {payload_content}, {legacy_log_type}) AS message,
                        {step_name_col} AS step_name,
                        {step_data_col} AS step_data,
                        {time_col} AS ts
                    FROM agent_logs
                    WHERE 1=1
                """
                params: dict[str, Any] = {"limit": limit}
                if agent_id:
                    base_sql += " AND " + run_col + " = :agent_id"
                    params["agent_id"] = agent_id
                if level:
                    base_sql += " AND LOWER(COALESCE(" + level_col + "::text, '')) = :level"
                    params["level"] = level.lower()
                base_sql += f" ORDER BY {time_col} DESC LIMIT :limit"

                result = await session.execute(text(base_sql), params)
                logs = result.fetchall()

                # Send initial logs
                for log in reversed(logs):  # Chronological order
                    log_data = {
                        "id": log.id,
                        "trace_id": log.trace_id,
                        "agent_run_id": log.agent_run_id,
                        "log_level": log.log_level,
                        "message": log.message,
                        "step_name": log.step_name,
                        "step_data": log.step_data,
                        "created_at": log.ts.isoformat() if log.ts else None,
                    }
                    yield f"data: {json.dumps(log_data)}\n\n"

                # Continue streaming new logs
                last_timestamp = logs[0].ts if logs else datetime.now(timezone.utc)

                while True:
                    await asyncio.sleep(1)  # Health log streaming interval - allowed

                    async with session_factory() as session:
                        poll_sql = base_sql.replace(
                            f" ORDER BY {time_col} DESC LIMIT :limit",
                            f" AND {time_col} > :last_timestamp ORDER BY {time_col} ASC",
                        )
                        poll_params = dict(params)
                        poll_params["last_timestamp"] = last_timestamp
                        poll_params.pop("limit", None)
                        result = await session.execute(text(poll_sql), poll_params)
                        new_logs = result.fetchall()

                        for log in new_logs:
                            log_data = {
                                "id": log.id,
                                "trace_id": log.trace_id,
                                "agent_run_id": log.agent_run_id,
                                "log_level": log.log_level,
                                "message": log.message,
                                "step_name": log.step_name,
                                "step_data": log.step_data,
                                "created_at": log.ts.isoformat() if log.ts else None,
                            }
                            yield f"data: {json.dumps(log_data)}\n\n"
                            last_timestamp = max(last_timestamp, log.ts)

        except Exception as e:
            log_structured("error", "log stream error", error=str(e))
            error_data = {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: error\ndata: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/pause")
async def pause_consumers():
    """Kill switch - pause all consumers."""
    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )

        # Send pause signal to all workers
        await redis_client.publish("consumer:control", json.dumps({"action": "pause"}))

        await redis_client.close()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "pause_signal_sent",
            "message": "Pause signal sent to all consumers",
        }

    except Exception as e:
        log_structured("error", "pause command error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/resume")
async def resume_consumers():
    """Resume all consumers."""
    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )

        # Send resume signal to all workers
        await redis_client.publish("consumer:control", json.dumps({"action": "resume"}))

        await redis_client.close()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "resume_signal_sent",
            "message": "Resume signal sent to all consumers",
        }

    except Exception as e:
        log_structured("error", "resume command error", error=str(e))
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
            total_backlog = info.get("length", 0)

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
                "backlog": total_backlog,
                "pending": pending_ack,
                "oldest_pending_age_seconds": oldest_age,
                "last_checked": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            # Handle missing streams gracefully
            health[stream] = {
                "status": "missing",
                "backlog": 0,
                "pending": 0,
                "oldest_pending_age_seconds": 0,
                "error": str(e),
                "last_checked": datetime.now(timezone.utc).isoformat(),
            }

    return health


async def get_worker_heartbeats(redis_client) -> dict[str, Any]:
    """Get worker heartbeat status."""
    try:
        heartbeat_data = await redis_client.hgetall("agent:heartbeats")

        heartbeats = {}
        for worker_id, data in heartbeat_data.items():
            try:
                parsed = json.loads(data)
                last_seen = datetime.fromisoformat(parsed["last_seen"])
                age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()

                heartbeats[worker_id] = {
                    **parsed,
                    "age_seconds": age_seconds,
                    "status": "alive" if age_seconds < 120 else "missing",
                }
            except (json.JSONDecodeError, ValueError):
                heartbeats[worker_id] = {"status": "invalid", "raw_data": data}

        return heartbeats

    except Exception as e:
        return {"error": str(e)}


async def get_db_pool_status() -> dict[str, Any]:
    """Get simplified DB pool status."""
    try:
        async with session_factory() as session:
            # Simple health check
            await session.execute(text("SELECT 1"))

            # In a real implementation, you'd get actual pool metrics
            # For now, return simulated status
            return {
                "active_connections": 15,  # Would come from engine.pool.status()
                "idle_connections": 35,
                "total_connections": 50,
                "pool_utilization_percent": 30,
                "status": "healthy",
            }

    except Exception as e:
        return {"status": "error", "error": str(e)}


def calculate_traffic_light(stream_health: dict, dlq_count: int, db_pool_status: dict) -> str:
    """Calculate traffic light status."""
    # Check for critical conditions
    if db_pool_status.get("status") == "error":
        return "red"

    if dlq_count > 0:
        return "yellow"

    # Check stream health
    for _stream, health in stream_health.items():
        if health.get("status") == "error":
            return "red"
        if health.get("oldest_msg_age_seconds", 0) > 60:
            return "yellow"
        if health.get("pending_ack", 0) > 100:
            return "yellow"

    # Check DB pool utilization
    if db_pool_status.get("pool_utilization_percent", 0) > 80:
        return "yellow"

    return "green"
