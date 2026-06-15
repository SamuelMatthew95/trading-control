from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from api.constants import FieldName
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.dashboard.utils import _as_dict, _timestamp_to_iso
from api.utils import now_iso


def _in_memory_trace_payload(trace_id: str) -> dict[str, Any]:
    """Return trace details from memory without touching Postgres."""
    store = get_runtime_store()
    runs = [
        {
            FieldName.ID: str(row.get(FieldName.ID) or row.get(FieldName.MSG_ID) or trace_id),
            "agent_name": row.get(FieldName.AGENT_NAME) or row.get(FieldName.SOURCE),
            FieldName.RUN_TYPE: row.get(FieldName.RUN_TYPE),
            "status": row.get(FieldName.STATUS),
            "input_data": row.get(FieldName.INPUT_DATA),
            "output_data": row.get(FieldName.OUTPUT_DATA),
            "execution_time_ms": row.get(FieldName.EXECUTION_TIME_MS),
            "created_at": _timestamp_to_iso(row.get(FieldName.CREATED_AT)),
        }
        for row in store.agent_runs
        if row.get(FieldName.TRACE_ID) == trace_id
    ]
    logs = []
    for row in store.agent_logs + store.event_history:
        payload = _as_dict(row.get(FieldName.PAYLOAD))
        if row.get(FieldName.TRACE_ID) != trace_id and payload.get(FieldName.TRACE_ID) != trace_id:
            continue
        logs.append(
            {
                FieldName.ID: str(
                    row.get(FieldName.ID) or row.get(FieldName.MSG_ID) or len(logs) + 1
                ),
                "log_type": row.get(FieldName.LOG_TYPE) or payload.get(FieldName.LOG_TYPE),
                "payload": payload or row.get(FieldName.PAYLOAD),
                "created_at": _timestamp_to_iso(
                    row.get(FieldName.CREATED_AT) or row.get(FieldName.TIMESTAMP)
                ),
            }
        )
    grades = [
        {
            FieldName.ID: str(row.get(FieldName.ID) or row.get(FieldName.MSG_ID) or trace_id),
            "agent_id": str(row.get(FieldName.AGENT_ID) or row.get(FieldName.AGENT_NAME) or ""),
            "grade_type": row.get(FieldName.GRADE_TYPE) or row.get(FieldName.GRADE),
            "score": row.get(FieldName.SCORE) or row.get(FieldName.SCORE_PCT),
            "metrics": row.get(FieldName.METRICS, {}),
            "created_at": _timestamp_to_iso(
                row.get(FieldName.CREATED_AT) or row.get(FieldName.TIMESTAMP)
            ),
        }
        for row in store.grade_history
        if row.get(FieldName.TRACE_ID) == trace_id
    ]
    return {
        "trace_id": trace_id,
        FieldName.AGENT_RUNS: runs,
        FieldName.AGENT_LOGS: logs,
        FieldName.AGENT_GRADES: grades,
        "timestamp": now_iso(),
        "source": "in_memory",
    }


async def get_trace_payload(trace_id: str) -> dict[str, Any]:
    """Return the full trace for a trace_id: agent_runs + agent_logs + agent_grades."""
    if not is_db_available():
        payload = _in_memory_trace_payload(trace_id)
        if (
            not payload[FieldName.AGENT_RUNS]
            and not payload[FieldName.AGENT_LOGS]
            and not payload[FieldName.AGENT_GRADES]
        ):
            raise HTTPException(status_code=404, detail="Trace not found") from None
        return payload

    try:
        async with AsyncSessionFactory() as session:
            run_result = await session.execute(
                text("""
                    SELECT id, source, run_type, status,
                           input_data, output_data, execution_time_ms, created_at
                    FROM agent_runs
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            runs = [
                {
                    FieldName.ID: str(r[0]),
                    "agent_name": r[1],
                    FieldName.RUN_TYPE: r[2],
                    "status": r[3],
                    "input_data": r[4],
                    "output_data": r[5],
                    "execution_time_ms": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in run_result.all()
            ]

            log_result = await session.execute(
                text("""
                    SELECT id, log_type, payload, created_at
                    FROM agent_logs
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            logs = [
                {
                    FieldName.ID: str(lg[0]),
                    "log_type": lg[1],
                    "payload": lg[2],
                    "created_at": lg[3].isoformat() if lg[3] else None,
                }
                for lg in log_result.all()
            ]

            grade_result = await session.execute(
                text("""
                    SELECT id, agent_id, grade_type, score, metrics, created_at
                    FROM agent_grades
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            grades = [
                {
                    FieldName.ID: str(g[0]),
                    "agent_id": str(g[1]),
                    "grade_type": g[2],
                    "score": float(g[3]) if g[3] is not None else None,
                    "metrics": g[4],
                    "created_at": g[5].isoformat() if g[5] else None,
                }
                for g in grade_result.all()
            ]

        if not runs and not logs and not grades:
            raise HTTPException(status_code=404, detail="Trace not found") from None

        return {
            "trace_id": trace_id,
            FieldName.AGENT_RUNS: runs,
            FieldName.AGENT_LOGS: logs,
            FieldName.AGENT_GRADES: grades,
            "timestamp": now_iso(),
        }
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "trace fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
