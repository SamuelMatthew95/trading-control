from __future__ import annotations

from fastapi import APIRouter

from api.observability import metrics_store

router = APIRouter(tags=["monitoring"])


@router.get("/api/monitoring/overview")
async def monitoring_overview():
    return metrics_store.snapshot()


@router.get("/api/monitoring/logs")
async def monitoring_logs(limit: int = 50):
    data = metrics_store.snapshot()
    return {"logs": data["recent_events"][:limit]}
