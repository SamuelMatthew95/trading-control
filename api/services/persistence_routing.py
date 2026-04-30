"""Deterministic persistence routing for the EventPipeline.

Selects an explicit route (DB / MEMORY / SKIP) before attempting any write so
that the pipeline never relies on exception-driven fallbacks.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from api.constants import (
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_LEARNING_EVENTS,
    STREAM_NOTIFICATIONS,
    STREAM_ORDERS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
)
from api.runtime_state import is_db_available
from api.schema_version import DB_SCHEMA_VERSION

_DB_STREAMS: frozenset[str] = frozenset(
    {
        STREAM_ORDERS,
        STREAM_EXECUTIONS,
        STREAM_AGENT_LOGS,
        STREAM_TRADE_PERFORMANCE,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_AGENT_GRADES,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_PROPOSALS,
        STREAM_NOTIFICATIONS,
    }
)


class PersistRoute(str, Enum):
    """Explicit persistence destination selected before any write attempt."""

    DB = "db"
    MEMORY = "memory"
    SKIP = "skip"


def should_route_agent_log_to_memory(event: dict[str, Any]) -> bool:
    """Return True when the agent_log event is missing fields required by SafeWriter.

    SafeWriter.write_agent_log validates:
      - schema_version == DB_SCHEMA_VERSION  (_validate_schema_v3)
      - source non-empty                     (_validate_schema_v3)
      - trace_id non-empty                   (_validate_schema_v3)
      - "level" key present                  (validate_payload)
      - "message" key present                (validate_payload)

    Any missing or invalid field would cause the DB write to raise, which the
    old pipeline caught silently.  Routing to MEMORY instead is explicit and
    auditable.
    """
    if event.get(FieldName.SCHEMA_VERSION) != DB_SCHEMA_VERSION:
        return True
    if not event.get(FieldName.SOURCE):
        return True
    if not event.get(FieldName.TRACE_ID):
        return True
    if not event.get(FieldName.LEVEL):
        return True
    if not event.get(FieldName.MESSAGE):
        return True
    return False


def determine_persist_route(stream: str, event: dict[str, Any]) -> PersistRoute:
    """Return the explicit persistence route for this (stream, event) pair.

    Decision order:
      1. Stream not handled by pipeline writers → SKIP.
      2. agent_logs stream with malformed payload → MEMORY.
      3. DB unavailable + agent_logs stream → MEMORY (never silently drop logs).
      4. DB unavailable for any other stream → SKIP.
      5. → DB.
    """
    if stream not in _DB_STREAMS:
        return PersistRoute.SKIP
    if stream == STREAM_AGENT_LOGS and should_route_agent_log_to_memory(event):
        return PersistRoute.MEMORY
    if not is_db_available():
        if stream == STREAM_AGENT_LOGS:
            return PersistRoute.MEMORY
        return PersistRoute.SKIP
    return PersistRoute.DB


def extract_agent_log_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return the inner payload dict from a stream event, or the event itself."""
    payload = event.get(FieldName.PAYLOAD)
    if isinstance(payload, dict):
        return payload
    return event


def build_memory_agent_log_row(msg_id: str, stream: str, event: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized in-memory agent_log row from a raw stream event."""
    payload = extract_agent_log_payload(event)
    return {
        FieldName.TRACE_ID: str(payload.get(FieldName.TRACE_ID) or msg_id),
        FieldName.SOURCE: str(payload.get(FieldName.SOURCE) or stream),
        FieldName.MESSAGE: str(payload.get(FieldName.MESSAGE) or ""),
        FieldName.LOG_LEVEL: str(
            payload.get(FieldName.LEVEL) or payload.get(FieldName.LOG_LEVEL) or "INFO"
        ),
        FieldName.SCHEMA_VERSION: str(payload.get(FieldName.SCHEMA_VERSION) or DB_SCHEMA_VERSION),
        FieldName.TIMESTAMP: str(payload.get(FieldName.TIMESTAMP) or ""),
    }
