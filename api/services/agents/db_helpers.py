"""Shared database write helpers used by multiple agent implementations.

Functions here isolate repeated INSERT patterns so each agent class stays
focused on its domain logic rather than raw SQL strings.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from api.database import AsyncSessionFactory
from api.observability import log_structured


async def write_agent_log(trace_id: str, log_type: str, payload: dict[str, Any]) -> None:
    """Insert a row into agent_logs. Logs a warning on failure and does not raise."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_logs (trace_id, log_type, payload)
                    VALUES (:trace_id, :log_type, CAST(:payload AS JSONB))
                """),
                {
                    "trace_id": trace_id,
                    "log_type": log_type,
                    "payload": json.dumps(payload, default=str),
                },
            )
            await session.commit()
    except Exception:
        log_structured(
            "warning", "agent_log_write_failed", log_type=log_type, trace_id=trace_id, exc_info=True
        )


async def write_grade_to_db(trace_id: str, score_pct: float, metrics: dict[str, Any]) -> None:
    """Insert a row into agent_grades. Logs a warning on failure and does not raise."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_grades
                        (grade_type, score, metrics, trace_id, schema_version, source)
                    VALUES ('pipeline', :score, CAST(:metrics AS JSONB), :trace_id, 'v3', 'grade_agent')
                """),
                {
                    "score": score_pct,
                    "metrics": json.dumps(metrics, default=str),
                    "trace_id": trace_id,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "grade_db_write_failed", trace_id=trace_id, exc_info=True)


async def persist_factor_ic(factor: str, ic_score: float, computed_at: str) -> None:
    """Insert an IC score snapshot into factor_ic_history."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO factor_ic_history (factor_name, ic_score, computed_at)
                    VALUES (:factor_name, :ic_score, :computed_at)
                """),
                {"factor_name": factor, "ic_score": ic_score, "computed_at": computed_at},
            )
            await session.commit()
    except Exception:
        log_structured("warning", "factor_ic_persist_failed", factor=factor, exc_info=True)


async def persist_proposal(proposal: dict[str, Any]) -> None:
    """Insert a proposal into agent_logs for dashboard query and audit trail."""
    trace_id = proposal.get("reflection_trace_id") or proposal.get("msg_id") or ""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_logs (trace_id, log_type, payload)
                    VALUES (:trace_id, 'proposal', CAST(:payload AS JSONB))
                """),
                {"trace_id": trace_id, "payload": json.dumps(proposal, default=str)},
            )
            await session.commit()
    except Exception:
        log_structured("warning", "proposal_persist_failed", exc_info=True)


async def get_last_reflection() -> dict[str, Any]:
    """Fetch the most recent reflection payload from agent_logs."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT payload FROM agent_logs
                    WHERE log_type = 'reflection'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
            )
            row = result.first()
            if row is None:
                return {}
            payload = row[0]
            if isinstance(payload, str):
                import json as _json

                return _json.loads(payload)
            return payload or {}
    except Exception:
        log_structured("error", "get_last_reflection_failed", exc_info=True)
        return {}
