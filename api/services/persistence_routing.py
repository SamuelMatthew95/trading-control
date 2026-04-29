from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from api.constants import STREAM_AGENT_LOGS, FieldName


class PersistRoute(str, Enum):
    SKIP = "skip"
    MEMORY = "memory"
    DB = "db"


def extract_agent_log_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get(FieldName.PAYLOAD)
    if isinstance(payload, dict):
        return payload
    return event


def should_route_agent_log_to_memory(event: dict[str, Any]) -> bool:
    payload = extract_agent_log_payload(event)
    level = payload.get("level") or payload.get(FieldName.LOG_LEVEL)
    message = payload.get(FieldName.MESSAGE)
    return not bool(level and message)


def determine_persist_route(
    *, stream: str, event: dict[str, Any], writer: Any | None
) -> PersistRoute:
    if writer is None:
        return PersistRoute.SKIP
    if stream == STREAM_AGENT_LOGS and should_route_agent_log_to_memory(event):
        return PersistRoute.MEMORY
    return PersistRoute.DB


def build_memory_agent_log_row(*, msg_id: str, event: dict[str, Any]) -> dict[str, Any]:
    payload = extract_agent_log_payload(event)
    message = (
        payload.get(FieldName.MESSAGE)
        or payload.get("event")
        or payload.get(FieldName.TYPE)
        or "agent_log"
    )
    return {
        "id": f"mem-{msg_id}",
        FieldName.AGENT_NAME: payload.get(FieldName.SOURCE)
        or payload.get(FieldName.AGENT)
        or payload.get(FieldName.AGENT_NAME)
        or "pipeline",
        FieldName.MESSAGE: str(message),
        FieldName.LOG_LEVEL: str(
            payload.get("level") or payload.get(FieldName.LOG_LEVEL) or "warning"
        ),
        FieldName.TRACE_ID: payload.get(FieldName.TRACE_ID),
        FieldName.LOG_TYPE: payload.get(FieldName.TYPE) or STREAM_AGENT_LOGS,
        "persist_path": "memory",
        "db_persist_status": "skipped_missing_required_fields",
        FieldName.TIMESTAMP: payload.get(FieldName.TIMESTAMP)
        or datetime.now(timezone.utc).isoformat(),
    }
