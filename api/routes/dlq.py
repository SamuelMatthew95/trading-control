from fastapi import APIRouter, HTTPException, Request

from api.constants import FieldName

router = APIRouter(tags=["dlq"])


def _get_dlq(request: Request):
    dlq = getattr(request.app.state, "dlq_manager", None)
    if dlq is None:
        raise HTTPException(status_code=503, detail="DLQ manager not available")
    return dlq


@router.get("/dlq")
async def get_dlq(request: Request):
    """Get all dead-letter queue items across all streams."""
    dlq = _get_dlq(request)
    items = await dlq.get_all()
    # Group by stream before returning:
    grouped: dict = {}
    for item in items:
        grouped.setdefault(item[FieldName.STREAM], []).append(item)
    return {FieldName.ITEMS: items, FieldName.TOTAL: len(items), FieldName.BY_STREAM: grouped}


@router.post("/dlq/{event_id}/replay")
async def replay_dlq_event(event_id: str, request: Request):
    """Replay a single DLQ event back into its stream."""
    dlq = _get_dlq(request)
    success = await dlq.replay(event_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found in DLQ")
    return {FieldName.REPLAYED: True, FieldName.EVENT_ID: event_id}


@router.delete("/dlq/{event_id}")
async def clear_dlq_event(event_id: str, request: Request):
    """Remove a single event from the DLQ."""
    dlq = _get_dlq(request)
    await dlq.clear(event_id)
    return {FieldName.CLEARED: True, FieldName.EVENT_ID: event_id}


@router.post("/dlq/replay-all")
async def replay_all_dlq(request: Request):
    """Replay all DLQ events back into their streams."""
    dlq = _get_dlq(request)
    items = await dlq.get_all()
    replayed = []
    failed = []
    for item in items:
        success = await dlq.replay(item[FieldName.EVENT_ID])
        if success:
            replayed.append(item[FieldName.EVENT_ID])
        else:
            failed.append(item[FieldName.EVENT_ID])
    return {FieldName.REPLAYED: replayed, FieldName.FAILED: failed, FieldName.TOTAL: len(items)}


@router.delete("/dlq")
async def clear_all_dlq(request: Request):
    """Clear all events from the DLQ."""
    dlq = _get_dlq(request)
    items = await dlq.get_all()
    for item in items:
        await dlq.clear(item[FieldName.EVENT_ID])
    return {FieldName.CLEARED: len(items)}
