from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from api.constants import FieldName
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available


async def get_recent_events_payload() -> dict[str, Any]:
    """Get last 10 events from events table, with in-memory fallback."""
    if not is_db_available():
        return {
            FieldName.EVENTS: get_runtime_store().get_events(limit=10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT id, event_type, entity_type, source, created_at
                    FROM events
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
            )
            rows = result.all()
            events = [
                {
                    FieldName.ID: str(row[0]),
                    "event_type": row[1],
                    "entity_type": row[2],
                    "source": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                }
                for row in rows
            ]
        return {
            FieldName.EVENTS: events,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "recent_events_db_unavailable", exc_info=True)
        store = get_runtime_store()
        return {
            FieldName.EVENTS: store.get_events(limit=10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_event_history_payload(safe_limit: int) -> dict[str, Any]:
    """Persisted event history + processed counts for operator visibility."""
    if not is_db_available():
        store = get_runtime_store()
        return {
            FieldName.STREAM_COUNTS: [],
            FieldName.PERSISTED_EVENTS: store.get_events(limit=safe_limit),
            FieldName.PERSISTED_LOGS: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }
    try:
        async with AsyncSessionFactory() as session:
            stream_counts = []
            try:
                counts_result = await session.execute(
                    text("""
                        SELECT
                            stream,
                            COUNT(*) AS processed_count,
                            MAX(created_at) AS last_processed_at
                        FROM processed_events
                        GROUP BY stream
                        ORDER BY processed_count DESC
                    """)
                )
                stream_counts = [
                    {
                        "stream": row[0],
                        FieldName.PROCESSED_COUNT: int(row[1] or 0),
                        FieldName.LAST_PROCESSED_AT: row[2].isoformat() if row[2] else None,
                    }
                    for row in counts_result.all()
                ]
            except Exception:
                stream_counts = []

            persisted_events = []
            try:
                events_result = await session.execute(
                    text("""
                        SELECT id, event_type, source, created_at
                        FROM events
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: safe_limit},
                )
                persisted_events = [
                    {
                        FieldName.ID: str(row[0]),
                        FieldName.KIND: row[1],
                        "source": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                    for row in events_result.all()
                ]
            except Exception:
                persisted_events = []

            persisted_logs = []
            try:
                logs_result = await session.execute(
                    text("""
                        SELECT id, trace_id, log_type, created_at
                        FROM agent_logs
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: safe_limit},
                )
                persisted_logs = [
                    {
                        FieldName.ID: str(row[0]),
                        "trace_id": row[1],
                        FieldName.KIND: row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                    for row in logs_result.all()
                ]
            except Exception:
                persisted_logs = []

        return {
            FieldName.STREAM_COUNTS: stream_counts,
            FieldName.PERSISTED_EVENTS: persisted_events,
            FieldName.PERSISTED_LOGS: persisted_logs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "event history failed", exc_info=True)
        if is_db_available():
            raise HTTPException(status_code=500, detail="Internal server error") from None
        store = get_runtime_store()
        return {
            FieldName.STREAM_COUNTS: [],
            FieldName.PERSISTED_EVENTS: store.get_events(limit=safe_limit),
            FieldName.PERSISTED_LOGS: [],
            "error": "event_history_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
