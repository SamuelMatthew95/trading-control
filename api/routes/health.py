from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from api.core.models import HealthResponse
from api.database import test_database_connection
from api.observability import metrics_store

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
async def health_check() -> dict:
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
    return payload
