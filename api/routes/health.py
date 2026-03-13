from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from api.core.models import HealthResponse
from api.database import test_database_connection

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> HealthResponse:
    return HealthResponse(
        status="running",
        orchestrator=True,
        database="unknown",
        timestamp=datetime.utcnow(),
        config_source="modular_app",
    )


@router.get("/api/health")
async def health_check() -> HealthResponse:
    db_healthy = await test_database_connection()
    return HealthResponse(
        status="healthy" if db_healthy else "unhealthy",
        orchestrator=True,
        database="connected" if db_healthy else "disconnected",
        timestamp=datetime.utcnow(),
        config_source="modular_app",
    )
