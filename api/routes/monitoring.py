from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from api.observability import metrics_store

router = APIRouter(tags=["monitoring"])


@router.get("/api/monitoring/metrics")
async def get_metrics():
    return {**metrics_store, "timestamp": datetime.utcnow().isoformat()}
