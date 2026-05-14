"""REST endpoints for recent trading decisions.

ReasoningAgent pushes every decision (including holds) to the Redis list
``decisions:recent``. The dashboard hydrates this on mount to show the recent
activity panel even after a websocket disconnect.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from api.services.redis_store import get_redis_store

router = APIRouter(tags=["decisions"])


@router.get("/decisions")
async def list_decisions(
    limit: int = Query(50, ge=1, le=500),
    action: str | None = Query(None, pattern="^(buy|sell|hold)$"),
) -> list[dict[str, Any]]:
    store = get_redis_store()
    if store is None:
        return []
    return await store.list_decisions(limit, action)


@router.get("/decisions/stats")
async def decisions_stats() -> dict[str, Any]:
    store = get_redis_store()
    if store is None:
        return {
            "total": 0,
            "last_hour": {"buys": 0, "sells": 0, "holds": 0},
            "last_decision": None,
        }
    return await store.decision_stats()
