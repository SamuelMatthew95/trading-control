"""REST endpoints for notifications stored in Redis.

Works in both memory mode (RedisStore is the source of truth) and DB mode
(RedisStore mirrors recent activity for fast catch-up after a reconnect).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query

from api.observability import log_structured
from api.services.redis_store import get_redis_store

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    store = get_redis_store()
    if store is None:
        return []
    return await store.list_notifications(limit)


@router.get("/notifications/unread-count")
async def unread_count() -> dict[str, int]:
    store = get_redis_store()
    if store is None:
        return {"count": 0}
    return {"count": await store.unread_count()}


# Use the ``:path`` converter so slashes in the id are captured. Trade
# notification ids come from build_trade_notification() and embed the symbol
# (e.g. ``trade:buy:BTC/USD:<trace>``); the default converter splits on ``/``
# and 404s for every slash-delimited symbol.
@router.post("/notifications/{notification_id:path}/read")
async def mark_read(
    notification_id: str = Path(..., min_length=1, max_length=256),
) -> dict[str, Any]:
    store = get_redis_store()
    if store is None:
        raise HTTPException(status_code=503, detail="redis_unavailable")
    ok = await store.mark_read(notification_id)
    if not ok:
        log_structured(
            "warning",
            "notification_mark_read_failed",
            notification_id=notification_id,
        )
        raise HTTPException(status_code=500, detail="failed_to_mark_read") from None
    return {"ok": True, "id": notification_id}
