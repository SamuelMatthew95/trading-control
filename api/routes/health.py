from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

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
                timestamp=datetime.utcnow(),
                config_source="modular_app",
            ).model_dump()
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
            timestamp=datetime.utcnow(),
            config_source="modular_app",
        ).model_dump()
        payload["telemetry"] = {
            "error_rate": telemetry["error_rate"],
            "avg_latency_ms": telemetry["avg_latency_ms"],
            "total_requests": telemetry["total_requests"],
        }
        
        return StandardResponse(
            success=True,
            data=payload
        ).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.options("/health")
async def health_options() -> Dict[str, Any]:
    """OPTIONS method for health endpoint."""
    return StandardResponse(
        success=True,
        data={"message": "Health endpoint supports GET and OPTIONS"}
    ).model_dump()
