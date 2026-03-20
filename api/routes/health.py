from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from api.core.models import HealthResponse
from api.database import test_database_connection
from api.observability import metrics_store

router = APIRouter(tags=["health"])


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None


async def _database_ready(request: Request) -> bool:
    try:
        engine = request.app.state.db_engine
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _redis_ready(request: Request) -> bool:
    try:
        redis_client = request.app.state.redis_client
        if redis_client is None:
            return False
        result = await redis_client.ping()
        return bool(result)
    except Exception:
        return False


@router.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint with standardized response format."""
    try:
        return StandardResponse(
            success=True,
            data=HealthResponse(
                status="running",
                orchestrator=True,
                database="unknown",
                timestamp=datetime.utcnow().isoformat(),
                config_source="modular_app",
            ).model_dump(),
        ).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
async def readiness_check(request: Request, response: Response) -> Dict[str, Any]:
    db_ready = await _database_ready(request)
    redis_ready = await _redis_ready(request)

    payload = {
        "status": "ok" if db_ready and redis_ready else "not_ready",
        "database": "connected" if db_ready else "disconnected",
        "redis": "connected" if redis_ready else "disconnected",
    }
    if not (db_ready and redis_ready):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@router.options("/health")
async def health_options() -> Dict[str, Any]:
    """OPTIONS method for health endpoint."""
    return StandardResponse(
        success=True, data={"message": "Health endpoint supports GET and OPTIONS"}
    ).model_dump()


@router.get("/system/health")
async def system_health() -> Dict[str, Any]:
    """System health endpoint for system monitoring."""
    try:
        db_healthy = await test_database_connection()
        telemetry = metrics_store.snapshot()

        from sqlalchemy import func, select

        from api.core.models import Run
        from api.database import get_async_session

        oldest_pending_age_seconds = None
        async with get_async_session() as session:
            oldest_pending = await session.execute(
                select(func.min(Run.created_at)).where(Run.scoring_status == "pending")
            )
            oldest_created_at = oldest_pending.scalar()
            if oldest_created_at:
                oldest_pending_age_seconds = (
                    datetime.utcnow() - oldest_created_at
                ).total_seconds()

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
                "timestamp": datetime.utcnow().isoformat(),
            },
        ).model_dump()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"System health check failed: {str(e)}"
        )
