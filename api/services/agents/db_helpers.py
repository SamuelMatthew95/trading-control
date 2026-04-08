"""Shared database write helpers used by multiple agent implementations.

Functions here isolate repeated INSERT patterns so each agent class stays
focused on its domain logic rather than raw SQL strings.
"""

from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import LogType
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.schema_version import DB_SCHEMA_VERSION


async def write_agent_log(
    trace_id: str,
    log_type: str,
    payload: dict[str, Any],
    *,
    agent_run_id: str | None = None,
) -> None:
    """Insert a row into agent_logs. Logs a warning on failure and does not raise."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_logs
                        (agent_run_id, trace_id, log_type, payload, schema_version)
                    VALUES
                        (:agent_run_id::uuid, :trace_id, :log_type, CAST(:payload AS JSONB),
                         :schema_version)
                """),
                {
                    "agent_run_id": agent_run_id,
                    "trace_id": trace_id,
                    "log_type": log_type,
                    "payload": json.dumps(payload, default=str),
                    "schema_version": DB_SCHEMA_VERSION,
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
                        (grade_type, score, metrics, trace_id, schema_version)
                    VALUES (
                        'pipeline',
                        :score,
                        CAST(:metrics AS JSONB),
                        :trace_id,
                        :schema_version
                    )
                """),
                {
                    "score": score_pct,
                    "metrics": json.dumps(metrics, default=str),
                    "trace_id": trace_id,
                    "schema_version": DB_SCHEMA_VERSION,
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
                    INSERT INTO agent_logs (trace_id, log_type, payload, schema_version)
                    VALUES (
                        :trace_id,
                        'proposal',
                        CAST(:payload AS JSONB),
                        :schema_version
                    )
                """),
                {
                    "trace_id": trace_id,
                    "payload": json.dumps(proposal, default=str),
                    "schema_version": DB_SCHEMA_VERSION,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "proposal_persist_failed", exc_info=True)


async def get_last_reflection() -> dict[str, Any]:
    """Fetch the most recent reflection payload from agent_logs."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text(f"""
                    SELECT payload FROM agent_logs
                    WHERE log_type = '{LogType.REFLECTION}'
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


# ---------------------------------------------------------------------------
# Agent instance lifecycle
# ---------------------------------------------------------------------------


async def register_agent_instance(instance_key: str, pool_name: str) -> str:
    """Insert a new agent_instances row and return its UUID string.

    Called once when an agent process starts.  Each restart produces a new
    UUID, so retired instances remain in the table for audit purposes.
    """
    instance_id = str(_uuid.uuid4())
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_instances
                        (id, instance_key, pool_name, status, started_at, schema_version)
                    VALUES
                        (:id, :key, :pool, 'active', NOW(), :schema_version)
                """),
                {
                    "id": instance_id,
                    "key": instance_key,
                    "pool": pool_name,
                    "schema_version": DB_SCHEMA_VERSION,
                },
            )
            await session.commit()
    except Exception:
        log_structured(
            "warning",
            "agent_instance_register_failed",
            instance_key=instance_key,
            exc_info=True,
        )
    return instance_id


async def retire_agent_instance(instance_id: str) -> None:
    """Mark an agent_instances row as retired with the current timestamp."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    UPDATE agent_instances
                    SET status = 'retired', retired_at = NOW()
                    WHERE id = :id
                """),
                {"id": instance_id},
            )
            await session.commit()
    except Exception:
        log_structured(
            "warning",
            "agent_instance_retire_failed",
            instance_id=instance_id,
            exc_info=True,
        )


async def increment_instance_event_count(instance_id: str) -> None:
    """Increment event_count for a running agent instance (best-effort)."""
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    UPDATE agent_instances
                    SET event_count = event_count + 1
                    WHERE id = :id AND status = 'active'
                """),
                {"id": instance_id},
            )
            await session.commit()
    except Exception:
        pass  # Non-critical counter — never raise


# ---------------------------------------------------------------------------
# Trade lifecycle
# ---------------------------------------------------------------------------


async def upsert_trade_lifecycle(
    execution_trace_id: str,
    *,
    symbol: str,
    side: str,
    qty: float | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    pnl: float | None = None,
    pnl_percent: float | None = None,
    order_id: str | None = None,
    signal_trace_id: str | None = None,
    decision_trace_id: str | None = None,
    grade_trace_id: str | None = None,
    reflection_trace_id: str | None = None,
    grade: str | None = None,
    grade_score: float | None = None,
    grade_label: str | None = None,
    status: str = "filled",
    filled_at: str | None = None,
    graded_at: str | None = None,
    reflected_at: str | None = None,
) -> None:
    """Insert or update one row in trade_lifecycle keyed on execution_trace_id.

    Uses INSERT … ON CONFLICT DO UPDATE so the same trace_id accumulates
    data as each downstream stage (grade, reflection) completes.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO trade_lifecycle (
                        id, symbol, side, qty, entry_price, exit_price,
                        pnl, pnl_percent, order_id,
                        signal_trace_id, decision_trace_id, execution_trace_id,
                        grade_trace_id, reflection_trace_id,
                        grade, grade_score, grade_label,
                        status, filled_at, graded_at, reflected_at,
                        schema_version, source, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :symbol, :side, :qty,
                        :entry_price, :exit_price,
                        :pnl, :pnl_percent, :order_id::uuid,
                        :signal_trace_id, :decision_trace_id, :execution_trace_id,
                        :grade_trace_id, :reflection_trace_id,
                        :grade, :grade_score, :grade_label,
                        :status,
                        :filled_at::timestamptz,
                        :graded_at::timestamptz,
                        :reflected_at::timestamptz,
                        :schema_version, 'execution_engine', NOW(), NOW()
                    )
                    ON CONFLICT (execution_trace_id)
                    DO UPDATE SET
                        qty              = COALESCE(EXCLUDED.qty,              trade_lifecycle.qty),
                        entry_price      = COALESCE(EXCLUDED.entry_price,      trade_lifecycle.entry_price),
                        exit_price       = COALESCE(EXCLUDED.exit_price,       trade_lifecycle.exit_price),
                        pnl              = COALESCE(EXCLUDED.pnl,              trade_lifecycle.pnl),
                        pnl_percent      = COALESCE(EXCLUDED.pnl_percent,      trade_lifecycle.pnl_percent),
                        order_id         = COALESCE(EXCLUDED.order_id,         trade_lifecycle.order_id),
                        grade_trace_id   = COALESCE(EXCLUDED.grade_trace_id,   trade_lifecycle.grade_trace_id),
                        reflection_trace_id = COALESCE(EXCLUDED.reflection_trace_id, trade_lifecycle.reflection_trace_id),
                        grade            = COALESCE(EXCLUDED.grade,            trade_lifecycle.grade),
                        grade_score      = COALESCE(EXCLUDED.grade_score,      trade_lifecycle.grade_score),
                        grade_label      = COALESCE(EXCLUDED.grade_label,      trade_lifecycle.grade_label),
                        status           = EXCLUDED.status,
                        filled_at        = COALESCE(EXCLUDED.filled_at,        trade_lifecycle.filled_at),
                        graded_at        = COALESCE(EXCLUDED.graded_at,        trade_lifecycle.graded_at),
                        reflected_at     = COALESCE(EXCLUDED.reflected_at,     trade_lifecycle.reflected_at),
                        updated_at       = NOW()
                """),
                {
                    "symbol": symbol,
                    "side": side.lower(),
                    "qty": qty,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                    "order_id": order_id,
                    "signal_trace_id": signal_trace_id,
                    "decision_trace_id": decision_trace_id,
                    "execution_trace_id": execution_trace_id,
                    "grade_trace_id": grade_trace_id,
                    "reflection_trace_id": reflection_trace_id,
                    "grade": grade,
                    "grade_score": grade_score,
                    "grade_label": grade_label,
                    "status": status,
                    "filled_at": filled_at or now_iso,
                    "graded_at": graded_at,
                    "reflected_at": reflected_at,
                    "schema_version": DB_SCHEMA_VERSION,
                },
            )
            await session.commit()
    except Exception:
        log_structured(
            "warning",
            "trade_lifecycle_upsert_failed",
            execution_trace_id=execution_trace_id,
            exc_info=True,
        )
