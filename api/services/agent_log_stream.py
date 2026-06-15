"""Shared SSE agent-log streamer behind /system/logs and /health/logs.

Both routes used to carry their own copy of the same ~110-line schema-detected
SQL generator. This module is the single implementation, parameterized by the
small differences the two endpoints expose (timestamp output key, trace_id
inclusion). It also fixes two defects the copies shared:

- the initial-query session is now closed before the poll loop starts — each
  connected SSE client used to pin one pool connection for the stream's
  entire lifetime;
- ``memory_mode_log_stream_response()`` gives every caller the same graceful
  memory-mode short-circuit instead of running SQL against an absent DB.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy import text

from api.constants import FieldName
from api.observability import log_structured
from api.utils import now_iso

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
}
_POLL_INTERVAL_SECONDS = 1


def memory_mode_log_stream_response() -> StreamingResponse:
    """One-frame SSE response for memory mode — no SQL is ever attempted."""

    async def _empty_generator() -> AsyncIterator[str]:
        yield _sse_frame({FieldName.MODE: "memory", FieldName.LOGS: []})

    return StreamingResponse(
        _empty_generator(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


def agent_log_stream_response(
    make_session: Callable[[], Any],
    *,
    limit: int,
    agent_id: str | None,
    level: str | None,
    ts_field: str,
    include_trace_id: bool,
) -> StreamingResponse:
    """SSE response streaming agent_logs rows: initial batch, then 1s polling.

    ``ts_field`` is the output key the row timestamp is serialized under
    (``timestamp`` for /system/logs, ``created_at`` for /health/logs);
    ``include_trace_id`` adds the trace_id column to each frame.
    """
    generator = _agent_log_generator(
        make_session,
        limit=limit,
        agent_id=agent_id,
        level=level,
        ts_field=ts_field,
        include_trace_id=include_trace_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream", headers=_SSE_HEADERS)


def _sse_frame(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _build_log_query(
    session: Any, agent_id: str | None, level: str | None
) -> tuple[str, dict[str, Any], str]:
    """Schema-detect agent_logs columns and build the base SELECT.

    The live table predates the migration system, so column names vary between
    deployments — probe information_schema and adapt instead of assuming.
    Returns (base_sql, filter_params, time_col).
    """
    col_result = await session.execute(
        text(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'agent_logs'
            """
        )
    )
    column_types = {row[0]: row[1] for row in col_result}
    available_columns = set(column_types)
    time_col = "created_at" if "created_at" in available_columns else "timestamp"
    run_col = "agent_run_id" if "agent_run_id" in available_columns else "source"
    level_col = "log_level" if "log_level" in available_columns else "log_type"
    trace_col = "trace_id" if "trace_id" in available_columns else "NULL"
    step_name_col = "step_name" if "step_name" in available_columns else "NULL"
    step_data_col = "step_data" if "step_data" in available_columns else "NULL"
    payload_is_json = column_types.get(FieldName.PAYLOAD) in {"json", "jsonb"}
    payload_message = "payload::jsonb->>'message'" if payload_is_json else "NULL"
    payload_content = "payload::jsonb->>'content'" if payload_is_json else "NULL"
    payload_text = "payload::text" if "payload" in available_columns else "NULL"
    legacy_log_type = "log_type" if "log_type" in available_columns else "NULL"
    message_col = "message" if "message" in available_columns else "NULL"

    base_sql = f"""
        SELECT
            id,
            {trace_col} AS trace_id,
            {run_col} AS agent_run_id,
            {level_col} AS log_level,
            COALESCE({message_col}, {payload_message}, {payload_content}, {payload_text}, {legacy_log_type}) AS message,
            {step_name_col} AS step_name,
            {step_data_col} AS step_data,
            {time_col} AS ts
        FROM agent_logs
        WHERE 1=1
    """
    params: dict[str, Any] = {}
    if agent_id:
        base_sql += " AND " + run_col + " = :agent_id"
        params[FieldName.AGENT_ID] = agent_id
    if level:
        base_sql += " AND LOWER(COALESCE(" + level_col + "::text, '')) = :level"
        params[FieldName.LEVEL] = level.lower()
    base_sql += f" ORDER BY {time_col} DESC LIMIT :limit"
    return base_sql, params, time_col


def _row_frame(log: Any, *, ts_field: str, include_trace_id: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        FieldName.ID: log.id,
        FieldName.AGENT_RUN_ID: log.agent_run_id,
        FieldName.LOG_LEVEL: log.log_level,
        FieldName.MESSAGE: log.message,
        FieldName.STEP_NAME: log.step_name,
        FieldName.STEP_DATA: log.step_data,
        ts_field: log.ts.isoformat() if log.ts else None,
    }
    if include_trace_id:
        data[FieldName.TRACE_ID] = log.trace_id
    return data


async def _agent_log_generator(
    make_session: Callable[[], Any],
    *,
    limit: int,
    agent_id: str | None,
    level: str | None,
    ts_field: str,
    include_trace_id: bool,
) -> AsyncIterator[str]:
    try:
        # Initial batch in its own short-lived session — the poll loop below
        # must not hold this connection open for the stream's lifetime.
        async with make_session() as session:
            base_sql, params, time_col = await _build_log_query(session, agent_id, level)
            result = await session.execute(text(base_sql), {**params, FieldName.LIMIT: limit})
            logs = result.fetchall()

        for log in reversed(logs):  # send in chronological order
            yield _sse_frame(_row_frame(log, ts_field=ts_field, include_trace_id=include_trace_id))

        last_timestamp = logs[0].ts if logs else datetime.now(timezone.utc)
        poll_sql = base_sql.replace(
            f" ORDER BY {time_col} DESC LIMIT :limit",
            f" AND {time_col} > :last_timestamp ORDER BY {time_col} ASC",
        )

        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)  # Log streaming interval - allowed
            async with make_session() as session:
                result = await session.execute(
                    text(poll_sql), {**params, FieldName.LAST_TIMESTAMP: last_timestamp}
                )
                new_logs = result.fetchall()
            for log in new_logs:
                yield _sse_frame(
                    _row_frame(log, ts_field=ts_field, include_trace_id=include_trace_id)
                )
                if log.ts is not None:
                    last_timestamp = max(last_timestamp, log.ts)
    except Exception as e:
        log_structured("error", "log stream error", exc_info=True)
        error_data = {
            FieldName.ERROR: str(e),
            FieldName.TIMESTAMP: now_iso(),
        }
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
