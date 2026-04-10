from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from api.constants import HealthStatus
from api.core.schemas import HealthResponse
from api.database import test_database_connection
from api.observability import log_structured, metrics_store
from api.runtime_state import get_runtime_store, runtime_mode

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None


async def _database_ready(request: Request) -> bool:
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
        from api.database import get_async_session

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
                "run": "SELECT MIN(created_at) FROM run WHERE scoring_status = :status",
                "runs": "SELECT MIN(created_at) FROM runs WHERE scoring_status = :status",
                "agent_runs": (
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
                timestamp=datetime.now(timezone.utc).isoformat(),
                services={
                    "orchestrator": "healthy",
                    "database": "unknown",
                    "config_source": "modular_app",
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
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
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

    return {
        "status": status,
        "database": "connected" if db_ready else "disconnected",
        "database_mode": runtime_mode(),
        "runtime_db_health": getattr(store, "last_health", "unknown"),
        "redis": "connected" if redis_ready else "disconnected",
        "pipeline_running": bool(pipeline and pipeline.status().get("running")),
        "active_ws_connections": (
            getattr(broadcaster, "active_connections", 0) if broadcaster else 0
        ),
        "last_error": pipeline.status().get("last_error") if pipeline else None,
        "recent_activity": pipeline.status().get("recent", [])[:5] if pipeline else [],
        "uptime_seconds": uptime_seconds,
        "check_time": now.isoformat(),
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
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
        }

    db_ready = await _database_ready(request)
    redis_ready = await _redis_ready(request)

    if db_ready and redis_ready:
        return {
            "status": "ready",
            "database": "connected",
            "redis": "connected",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
        }
    # Return degraded status instead of HTTP 503
    return {
        "status": "degraded",
        "message": "Some dependencies are not ready",
        "database": "connected" if db_ready else "disconnected",
        "redis": "connected" if redis_ready else "disconnected",
        "uptime_seconds": uptime_seconds,
        "check_time": now.isoformat(),
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
                "database_connected": db_healthy,
                "feedback_jobs_pending": 0,
                "feedback_jobs_failed": 0,
                "scoring_pending": 0,
                "scoring_failed": 0,
                "oldest_pending_score_age_seconds": oldest_pending_age_seconds,
                "telemetry": {
                    "error_rate": telemetry["error_rate"],
                    "avg_latency_ms": telemetry["avg_latency_ms"],
                    "total_requests": telemetry["total_requests"],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ).model_dump()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"System health check failed: {str(e)}"
        ) from None
