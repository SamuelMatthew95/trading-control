"""
Observability API - System status and real-time logs.

Aggregates stream lag, agent pulse, and database health.
Provides SSE streaming of agent logs.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings
from ..core.models import Order, SystemMetrics
from ..observability import log_structured
from ..redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])

settings = get_settings()

# Database connection
database_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(database_url, pool_size=10, max_overflow=20)
session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@router.get("/status")
async def get_system_status():
    """Aggregate system status including stream lag, agent pulse, and database health."""

    async with session_factory() as session:
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
                "last_level": row.last_level,
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

        pending_orders = order_stats.get("pending", 0)
        filled_orders = order_stats.get("filled", 0)

        # Stream Lag calculation
        stream_lag = await get_stream_lag()

        # Sanitize lag values to prevent NaN
        sanitized_lag = {}
        for stream, data in stream_lag.items():
            if isinstance(data, dict):
                sanitized_lag[stream] = {
                    "lag_ms": data.get("lag_ms", 0) or 0,
                    "lag_seconds": data.get("lag_seconds", 0) or 0,
                    "head_id": data.get("head_id", ""),
                    "last_processed_id": data.get("last_processed_id", ""),
                    "error": data.get("error"),
                }
            else:
                sanitized_lag[stream] = data

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_pulse": agent_pulse,
            "database_health": {
                "pending_orders_last_hour": pending_orders,
                "filled_orders_last_hour": filled_orders,
                "total_orders_last_hour": pending_orders + filled_orders,
            },
            "stream_lag": sanitized_lag,
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
                        if group.get("name") == "trading_workers":
                            last_delivered = group.get("last-delivered-id", "0-0")
                            # Calculate lag (simplified - just comparing timestamps)
                            head_timestamp = int(head_id.split("-")[0])
                            last_timestamp = int(last_delivered.split("-")[0])
                            lag_ms = head_timestamp - last_timestamp

                            lag_info[stream] = {
                                "head_id": head_id,
                                "last_processed_id": last_delivered,
                                "lag_ms": lag_ms,
                                "lag_seconds": lag_ms / 1000,
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

    async def log_generator():
        """SSE generator for agent logs."""
        try:
            # Get initial logs
            async with session_factory() as session:
                col_result = await session.execute(
                    text(
                        """
                        SELECT column_name, udt_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'agent_logs'
                        """
                    )
                )
                column_types = {row[0]: row[1] for row in col_result}
                available_columns = set(column_types)
                time_col = "created_at" if "created_at" in available_columns else "timestamp"
                run_col = "agent_run_id" if "agent_run_id" in available_columns else "source"
                level_col = "log_level" if "log_level" in available_columns else "log_type"
                trace_col = "trace_id" if "trace_id" in available_columns else "NULL"
                step_name_col = "step_name" if "step_name" in available_columns else "NULL"
                step_data_col = "step_data" if "step_data" in available_columns else "NULL"
                payload_is_json = column_types.get("payload") in {"json", "jsonb"}
                payload_message = "payload::jsonb->>'message'" if payload_is_json else "NULL"
                payload_content = "payload::jsonb->>'content'" if payload_is_json else "NULL"
                payload_text = "payload::text" if "payload" in available_columns else "NULL"
                legacy_log_type = "log_type" if "log_type" in available_columns else "NULL"
                message_col = "message" if "message" in available_columns else "NULL"
                base_sql = f"""
                    SELECT
                        id,
                        {trace_col} AS trace_id,
                        {run_col} AS agent_run_id,
                        {level_col} AS log_level,
                        COALESCE({message_col}, {payload_message}, {payload_content}, {payload_text}, {legacy_log_type}) AS message,
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
                for log in reversed(logs):  # Send in chronological order
                    log_data = {
                        "id": log.id,
                        "agent_run_id": log.agent_run_id,
                        "log_level": log.log_level,
                        "message": log.message,
                        "step_name": log.step_name,
                        "step_data": log.step_data,
                        "timestamp": log.ts.isoformat() if log.ts else None,
                    }
                    yield f"data: {json.dumps(log_data)}\n\n"

                # Continue streaming new logs
                last_timestamp = logs[0].ts if logs else datetime.now(timezone.utc)

                while True:
                    await asyncio.sleep(1)  # Log streaming interval - allowed

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
                                "agent_run_id": log.agent_run_id,
                                "log_level": log.log_level,
                                "message": log.message,
                                "step_name": log.step_name,
                                "step_data": log.step_data,
                                "timestamp": log.ts.isoformat() if log.ts else None,
                            }
                            yield f"data: {json.dumps(log_data)}\n\n"
                            last_timestamp = max(last_timestamp, log.ts)

        except Exception as e:
            log_structured("error", "log stream error", exc_info=True)
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


@router.get("/metrics")
async def get_system_metrics(
    metric_name: str = Query(None, description="Filter by metric name"),
    hours: int = Query(1, description="Hours of history to fetch"),
):
    """Get system metrics for monitoring."""

    async with session_factory() as session:
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
                    "metric_name": m.metric_name,
                    "metric_value": float(m.metric_value or 0),  # Guard against NaN/None
                    "metric_unit": m.metric_unit,
                    "tags": m.tags or {},  # Guard against None
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in metrics
            ],
            "count": len(metrics),
        }


@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    try:
        # Test database connection
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

        # Test Redis connection
        redis_client = await get_redis()
        await redis_client.ping()

        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected",
            "redis": "connected",
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
