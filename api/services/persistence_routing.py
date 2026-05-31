"""Deterministic persistence routing for the EventPipeline.

Selects an explicit route (DB / MEMORY / SKIP) before attempting any write so
that the pipeline never relies on exception-driven fallbacks.

When the DB is unavailable every handled stream routes to MEMORY so no
event is silently dropped.  Each stream dispatches to its dedicated
InMemoryStore method; streams without a dedicated bucket fall back to
add_event().
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from api.in_memory_store import InMemoryStore

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

# Streams whose durable Postgres row is owned by the producing agent, NOT the
# pipeline:
#   - GradeAgent persists grades (write_grade_to_db)
#   - ReflectionAgent persists reflections (write_agent_log + persist_reflection_record)
#   - StrategyProposer persists proposals (persist_proposal)
#   - ICUpdater owns factor IC history
#   - ExecutionEngine persists orders/positions/fills directly (order_writer +
#     upsert_position_db + upsert_trade_lifecycle), so STREAM_EXECUTIONS
#     write_execution is redundant (and always failed on the Position NOT NULL
#     constraint because the fill payload carries no new_quantity/avg_cost).
# The EventPipeline's redundant SafeWriter call for these never actually
# succeeded — the stream payloads omit fields the validators require
# (agent_id/agent_run_id/grade_type, ic_value, trace_id, insights, position
# quantity…), so it only ever raised and logged "pipeline_persist_skipped".
# Skip the DB write when the DB is up (the agent already wrote the row); the
# pipeline still broadcasts the event, and the MEMORY fallback when the DB is
# down is unchanged so the dashboard keeps hydrating in memory mode.
_AGENT_OWNED_DB_STREAMS: frozenset[str] = frozenset(
    {
        STREAM_AGENT_GRADES,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_PROPOSALS,
        STREAM_EXECUTIONS,
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
      2. agent_logs stream with malformed payload → MEMORY (even when DB is up).
      3. DB unavailable → MEMORY for all handled streams (never silently drop).
      4. Agent-owned stream (DB up) → SKIP: the producing agent already wrote the
         durable row; the pipeline only broadcasts it (never double-persists).
      5. → DB.
    """
    if stream not in _DB_STREAMS:
        return PersistRoute.SKIP
    if stream == STREAM_AGENT_LOGS and should_route_agent_log_to_memory(event):
        return PersistRoute.MEMORY
    if not is_db_available():
        return PersistRoute.MEMORY
    if stream in _AGENT_OWNED_DB_STREAMS:
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


def write_event_to_memory(
    stream: str, msg_id: str, event: dict[str, Any], store: InMemoryStore
) -> None:
    """Write a pipeline event to the appropriate InMemoryStore bucket.

    Each stream maps to its dedicated store method so the in-memory snapshot
    mirrors the same shape as the corresponding Postgres table.  Streams
    without a dedicated bucket fall through to add_event() so nothing is lost.
    """
    if stream == STREAM_AGENT_LOGS:
        store.add_agent_log(build_memory_agent_log_row(msg_id, stream, event))
    elif stream == STREAM_ORDERS:
        store.add_order(event)
    elif stream == STREAM_AGENT_GRADES:
        store.add_grade(event)
    elif stream == STREAM_LEARNING_EVENTS:
        store.add_vector_memory(event)
    elif stream == STREAM_TRADE_PERFORMANCE:
        store.upsert_trade_fill(event)
    else:
        # STREAM_EXECUTIONS, STREAM_RISK_ALERTS, STREAM_FACTOR_IC_HISTORY,
        # STREAM_REFLECTION_OUTPUTS, STREAM_PROPOSALS, STREAM_NOTIFICATIONS
        store.add_event(
            {
                FieldName.ID: msg_id,
                FieldName.KIND: stream,
                FieldName.SOURCE: str(event.get(FieldName.SOURCE) or stream),
                FieldName.CREATED_AT: str(event.get(FieldName.TIMESTAMP) or ""),
                FieldName.PAYLOAD: event,
            }
        )
