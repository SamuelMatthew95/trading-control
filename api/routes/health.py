from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from api.config import settings
from api.constants import FieldName, HealthStatus
from api.core.schemas import HealthResponse
from api.database import get_async_session, test_database_connection
from api.observability import log_structured, metrics_store
from api.redis_client import redis_pool_stats
from api.runtime_state import get_runtime_store, runtime_mode
from api.utils import now_iso

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None


async def _database_ready(request: Request) -> bool:
    # When the operator has explicitly requested memory mode, the DB is
    # known-absent. Skip the connection attempt so we don't spam DNS-failure
    # warnings every health probe.
    if settings.USE_MEMORY_MODE:
        return False
    try:
        engine = request.app.state.db_engine
        async with engine.connect() as connection:
            await asyncio.wait_for(connection.execute(text("SELECT 1")), timeout=2.0)
        return True
    except Exception:
        log_structured("warning", "database health check failed", exc_info=True)
        return False


async def _redis_ready(request: Request) -> bool:
    try:
        redis_client = request.app.state.redis_client
        if redis_client is None:
            return False
        result = await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        return bool(result)
    except Exception:
        log_structured("warning", "redis health check failed", exc_info=True)
        return False


async def _oldest_pending_score_age_seconds() -> float | None:
    """Return the age in seconds of the oldest pending score job when available."""
    try:
        async with get_async_session() as session:
            table_result = await session.execute(
                text("""
                    SELECT table_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND column_name = 'scoring_status'
                      AND table_name IN ('run', 'runs', 'agent_runs')
                    ORDER BY CASE table_name
                        WHEN 'run' THEN 1
                        WHEN 'runs' THEN 2
                        WHEN 'agent_runs' THEN 3
                        ELSE 99
                    END
                    LIMIT 1
                    """)
            )
            table_name = table_result.scalar()
            if not table_name:
                return None

            query_by_table = {
                FieldName.RUN: "SELECT MIN(created_at) FROM run WHERE scoring_status = :status",
                FieldName.RUNS: "SELECT MIN(created_at) FROM runs WHERE scoring_status = :status",
                FieldName.AGENT_RUNS: (
                    "SELECT MIN(created_at) FROM agent_runs WHERE scoring_status = :status"
                ),
            }
            query = query_by_table.get(table_name)
            if not query:
                return None

            oldest_result = await session.execute(text(query), {"status": "pending"})
            oldest_created_at = oldest_result.scalar()

            if oldest_created_at is None:
                return None

            now = datetime.now(timezone.utc)
            if oldest_created_at.tzinfo is None:
                oldest_created_at = oldest_created_at.replace(tzinfo=timezone.utc)
            return (now - oldest_created_at).total_seconds()
    except Exception:
        # Compatibility metric is best-effort and should never fail health checks.
        return None


@router.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint with standardized response format."""
    try:
        return StandardResponse(
            success=True,
            data=HealthResponse(
                status="running",
                timestamp=now_iso(),
                services={
                    FieldName.ORCHESTRATOR: "healthy",
                    FieldName.DATABASE: "unknown",
                    FieldName.CONFIG_SOURCE: "modular_app",
                },
            ).model_dump(),
        ).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") from None


@router.get("/health")
async def health_check(request: Request) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    # Check startup grace period (60 seconds)
    uptime_seconds = (now - PROCESS_START_TIME).total_seconds()
    if uptime_seconds < 60:
        return {
            "status": "starting",
            "message": "Service is warming up",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }

    # Check dependencies
    db_ready = await _database_ready(request)
    redis_ready = await _redis_ready(request)
    pipeline = getattr(request.app.state, "event_pipeline", None)
    broadcaster = getattr(request.app.state, "websocket_broadcaster", None)

    # Determine overall status
    if db_ready and redis_ready:
        status = HealthStatus.HEALTHY
    else:
        status = HealthStatus.DEGRADED

    store = getattr(request.app.state, "in_memory_store", get_runtime_store())

    if settings.USE_MEMORY_MODE:
        # Operator-declared memory mode is not "degraded" — it's the intended
        # runtime state. Report as healthy so monitoring doesn't alarm.
        status = HealthStatus.HEALTHY if redis_ready else HealthStatus.DEGRADED
        db_label = "memory"
    else:
        db_label = "connected" if db_ready else "disconnected"

    return {
        "status": status,
        FieldName.DATABASE: db_label,
        FieldName.DATABASE_MODE: runtime_mode(),
        FieldName.RUNTIME_DB_HEALTH: getattr(store, "last_health", "unknown"),
        FieldName.REDIS: "connected" if redis_ready else "disconnected",
        # Pure in-process counters (no Redis I/O) — readable even when the pool
        # is saturated and the ping above is starving. in_use == max means
        # callers are queueing on BlockingConnectionPool.get_connection (the
        # "No connection available." starvation mode).
        FieldName.REDIS_POOL: redis_pool_stats(),
        FieldName.PIPELINE_RUNNING: bool(pipeline and pipeline.status().get(FieldName.RUNNING)),
        FieldName.ACTIVE_WS_CONNECTIONS: (
            getattr(broadcaster, "active_connections", 0) if broadcaster else 0
        ),
        FieldName.LAST_ERROR: pipeline.status().get(FieldName.LAST_ERROR) if pipeline else None,
        FieldName.RECENT_ACTIVITY: pipeline.status().get(FieldName.RECENT, [])[:5]
        if pipeline
        else [],
        FieldName.UPTIME_SECONDS: uptime_seconds,
        FieldName.CHECK_TIME: now.isoformat(),
    }


@router.get("/readiness")
async def readiness_check(request: Request, response: Response) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    # Check startup grace period (60 seconds)
    uptime_seconds = (now - PROCESS_START_TIME).total_seconds()
    if uptime_seconds < 60:
        return {
            "status": "starting",
            "message": "Service is warming up",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }

    db_ready = await _database_ready(request)
    redis_ready = await _redis_ready(request)

    # Memory mode is a first-class runtime — only Redis is required for readiness.
    if settings.USE_MEMORY_MODE:
        if redis_ready:
            return {
                "status": "ready",
                FieldName.DATABASE: "memory",
                FieldName.REDIS: "connected",
                FieldName.UPTIME_SECONDS: uptime_seconds,
                FieldName.CHECK_TIME: now.isoformat(),
            }
        return {
            "status": "degraded",
            "message": "Redis unavailable in memory mode",
            FieldName.DATABASE: "memory",
            FieldName.REDIS: "disconnected",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }

    if db_ready and redis_ready:
        return {
            "status": "ready",
            FieldName.DATABASE: "connected",
            FieldName.REDIS: "connected",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }
    # Return degraded status instead of HTTP 503
    return {
        "status": "degraded",
        "message": "Some dependencies are not ready",
        FieldName.DATABASE: "connected" if db_ready else "disconnected",
        FieldName.REDIS: "connected" if redis_ready else "disconnected",
        FieldName.UPTIME_SECONDS: uptime_seconds,
        FieldName.CHECK_TIME: now.isoformat(),
    }


@router.options("/health")
async def health_options() -> dict[str, Any]:
    """OPTIONS method for health endpoint."""
    return StandardResponse(
        success=True, data={"message": "Health endpoint supports GET and OPTIONS"}
    ).model_dump()


@router.get("/system/health")
async def system_health() -> dict[str, Any]:
    """System health endpoint for system monitoring."""
    try:
        db_healthy = await test_database_connection()
        telemetry = metrics_store.snapshot()

        oldest_pending_age_seconds = await _oldest_pending_score_age_seconds()

        return StandardResponse(
            success=True,
            data={
                "status": "healthy" if db_healthy else "unhealthy",
                FieldName.DATABASE_CONNECTED: db_healthy,
                FieldName.FEEDBACK_JOBS_PENDING: 0,
                FieldName.FEEDBACK_JOBS_FAILED: 0,
                FieldName.SCORING_PENDING: 0,
                FieldName.SCORING_FAILED: 0,
                FieldName.OLDEST_PENDING_SCORE_AGE_SECONDS: oldest_pending_age_seconds,
                FieldName.TELEMETRY: {
                    FieldName.ERROR_RATE: telemetry[FieldName.ERROR_RATE],
                    FieldName.AVG_LATENCY_MS: telemetry[FieldName.AVG_LATENCY_MS],
                    FieldName.TOTAL_REQUESTS: telemetry[FieldName.TOTAL_REQUESTS],
                },
                "timestamp": now_iso(),
            },
        ).model_dump()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"System health check failed: {str(e)}"
        ) from None
