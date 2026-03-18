from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.models import HealthResponse
from api.database import test_database_connection
from api.observability import metrics_store

router = APIRouter(tags=["health"])


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None


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
async def health_check() -> Dict[str, Any]:
    """Health check endpoint with standardized response format."""
    try:
        db_healthy = await test_database_connection()
        telemetry = metrics_store.snapshot()
        payload = HealthResponse(
            status="healthy" if db_healthy else "unhealthy",
            orchestrator=True,
            database="connected" if db_healthy else "disconnected",
            timestamp=datetime.utcnow().isoformat(),
            config_source="modular_app",
        ).model_dump()
        payload["telemetry"] = {
            "error_rate": telemetry["error_rate"],
            "avg_latency_ms": telemetry["avg_latency_ms"],
            "total_requests": telemetry["total_requests"],
        }

        return StandardResponse(success=True, data=payload).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


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

        # Calculate oldest pending score age
        from api.database import get_async_session
        from api.core.models import Run
        from datetime import datetime
        from sqlalchemy import select, func

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
                "feedback_jobs_pending": 0,  # TODO: Implement actual feedback job counting
                "feedback_jobs_failed": 0,  # TODO: Implement actual feedback job counting
                "scoring_pending": 0,  # TODO: Implement actual scoring pending counting
                "scoring_failed": 0,  # TODO: Implement actual scoring failed counting
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
