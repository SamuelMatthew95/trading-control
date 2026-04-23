"""Shared database write helpers used by multiple agent implementations.

DB routing:
  - is_db_available() is checked upfront in every public function.
  - DB mode: performs SQL writes via AsyncSessionFactory.
  - Memory mode: writes to InMemoryStore; no DB session opened at all.
"""

from __future__ import annotations

import asyncio
import json
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import SOURCE_DB_HELPERS, SOURCE_EXECUTION, FieldName, GradeType, LogType
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.schema_version import DB_SCHEMA_VERSION


async def write_agent_log(
    trace_id: str,
    log_type: str,
    payload: dict[str, Any],
    *,
    agent_run_id: str | None = None,
) -> None:
    """Insert a row into agent_logs.

    Memory mode: GRADE logs go to grade_history; all others go to event_history.
    DB mode: INSERT into agent_logs table.
    """
    if not is_db_available():
        store = get_runtime_store()
        if log_type == LogType.GRADE:
            store.add_grade(
                {
                    "trace_id": trace_id,
                    "grade": payload.get(FieldName.GRADE),
                    "score": payload.get(FieldName.SCORE),
                    "score_pct": payload.get(FieldName.SCORE_PCT),
                    "metrics": payload.get(FieldName.METRICS, {}),
                    "fills_graded": payload.get("fills_graded"),
                    "timestamp": payload.get(FieldName.TIMESTAMP)
                    or datetime.now(timezone.utc).isoformat(),
                }
            )
        else:
            store.add_event(
                {
                    "log_type": log_type,
                    "trace_id": trace_id,
                    "agent_run_id": agent_run_id,
                    "payload": payload,
                }
            )
        # Also surface on the dashboard Agent Thought Stream — extract the most
        # meaningful human-readable message field and a confidence if present.
        message = (
            payload.get(FieldName.MESSAGE)
            or payload.get(FieldName.CONTENT)
            or payload.get(FieldName.REASON)
            or payload.get(FieldName.PRIMARY_EDGE)
            or log_type
        )
        store.add_agent_log(
            {
                "id": f"mem-{len(store.agent_logs) + 1}",
                "agent_name": payload.get(FieldName.SOURCE)
                or payload.get(FieldName.AGENT)
                or payload.get(FieldName.AGENT_NAME)
                or log_type,
                "message": message,
                "log_level": "info",
                "trace_id": trace_id,
                "log_type": log_type,
                "confidence": payload.get(FieldName.CONFIDENCE),
                "timestamp": payload.get(FieldName.TIMESTAMP)
                or datetime.now(timezone.utc).isoformat(),
            }
        )
        return

    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_logs
                        (agent_run_id, trace_id, log_type, payload, schema_version, source)
                    VALUES
                        (:agent_run_id, :trace_id, :log_type, CAST(:payload AS JSONB),
                         :schema_version, :source)
                """),
                {
                    "agent_run_id": agent_run_id,
                    "trace_id": trace_id,
                    "log_type": log_type,
                    "payload": json.dumps(payload, default=str),
                    "schema_version": DB_SCHEMA_VERSION,
                    "source": SOURCE_DB_HELPERS,
                },
            )
            await session.commit()
    except Exception:
        log_structured(
            "warning", "agent_log_write_failed", log_type=log_type, trace_id=trace_id, exc_info=True
        )


async def write_grade_to_db(trace_id: str, score_pct: float, metrics: dict[str, Any]) -> None:
    """Insert a row into agent_grades.

    Memory mode: writes to InMemoryStore grade_history.
    DB mode: INSERT into agent_grades table.
    """
    # Convert score to grade letter
    from api.services.agents.scoring import score_to_grade

    grade = score_to_grade(score_pct)

    if not is_db_available():
        get_runtime_store().add_grade(
            {
                "trace_id": trace_id,
                "grade": grade,
                "score": score_pct,
                "score_pct": round(score_pct, 2) if score_pct is not None else None,
                "metrics": metrics,
                "fills_graded": metrics.get("fills_graded"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return

    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_grades
                        (grade_type, score, metrics, trace_id, schema_version, source)
                    VALUES (
                        :grade_type,
                        :score,
                        CAST(:metrics AS JSONB),
                        :trace_id,
                        :schema_version,
                        :source
                    )
                """),
                {
                    "grade_type": GradeType.OVERALL,
                    "score": score_pct,
                    "metrics": json.dumps(metrics, default=str),
                    "trace_id": trace_id,
                    "schema_version": DB_SCHEMA_VERSION,
                    "source": SOURCE_DB_HELPERS,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "grade_db_write_failed", trace_id=trace_id, exc_info=True)


async def persist_factor_ic(factor: str, ic_score: float, computed_at: str) -> None:
    """Insert an IC score snapshot into factor_ic_history. No-op in memory mode."""
    if not is_db_available():
        return
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
    """Insert a proposal into agent_logs for dashboard query and audit trail.

    Memory mode: writes to InMemoryStore event_history.
    """
    trace_id = proposal.get("reflection_trace_id") or proposal.get(FieldName.MSG_ID) or ""
    if not is_db_available():
        get_runtime_store().add_event(
            {
                "log_type": LogType.PROPOSAL,
                "trace_id": trace_id,
                "payload": proposal,
            }
        )
        return
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_logs (trace_id, log_type, payload, schema_version, source)
                    VALUES (
                        :trace_id,
                        :log_type,
                        CAST(:payload AS JSONB),
                        :schema_version,
                        :source
                    )
                """),
                {
                    "trace_id": trace_id,
                    "log_type": LogType.PROPOSAL,
                    "payload": json.dumps(proposal, default=str),
                    "schema_version": DB_SCHEMA_VERSION,
                    "source": SOURCE_DB_HELPERS,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "proposal_persist_failed", exc_info=True)


async def get_last_reflection() -> dict[str, Any]:
    """Fetch the most recent reflection payload from agent_logs.

    Returns {} in memory mode (no history is persisted).
    """
    if not is_db_available():
        return {}
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT payload FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"log_type": LogType.REFLECTION},
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


_REGISTER_MAX_ATTEMPTS = 3
_REGISTER_BACKOFF_BASE_S = 0.2


async def register_agent_instance(instance_key: str, pool_name: str) -> str:
    """Insert a new agent_instances row and return its UUID string.

    In memory mode: returns a generated UUID without any DB write.

    DB mode: retries the INSERT up to ``_REGISTER_MAX_ATTEMPTS`` times with
    exponential backoff. Without retries a single transient DB hiccup at
    startup left the agent running with an ``_instance_id`` that was never
    persisted — every downstream ``increment_instance_event_count`` then
    silently matched zero rows and heartbeats lived without a lifecycle
    record. The final failure is logged at ERROR level so ops notices.
    """
    instance_id = str(_uuid.uuid4())
    if not is_db_available():
        return instance_id

    last_exc: Exception | None = None
    for attempt in range(1, _REGISTER_MAX_ATTEMPTS + 1):
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text("""
                        INSERT INTO agent_instances
                            (id, instance_key, pool_name, status, started_at, schema_version)
                        VALUES
                            (:id, :key, :pool, 'active', NOW(), :schema_version)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": instance_id,
                        "key": instance_key,
                        "pool": pool_name,
                        "schema_version": DB_SCHEMA_VERSION,
                    },
                )
                await session.commit()
            return instance_id
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _REGISTER_MAX_ATTEMPTS:
                log_structured(
                    "warning",
                    "agent_instance_register_retry",
                    instance_key=instance_key,
                    attempt=attempt,
                    exc_info=True,
                )
                await asyncio.sleep(_REGISTER_BACKOFF_BASE_S * (2 ** (attempt - 1)))

    log_structured(
        "error",
        "agent_instance_register_failed",
        instance_key=instance_key,
        pool_name=pool_name,
        attempts=_REGISTER_MAX_ATTEMPTS,
        last_error=str(last_exc) if last_exc else "unknown",
    )
    return instance_id


async def retire_agent_instance(instance_id: str) -> None:
    """Mark an agent_instances row as retired. No-op in memory mode."""
    if not is_db_available():
        return
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
    """Increment event_count for a running agent instance. No-op in memory mode."""
    if not is_db_available():
        return
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

    Memory mode: stores a compact order record in InMemoryStore so the
    dashboard fallback snapshot can show real trade activity.
    """
    if not is_db_available():
        store = get_runtime_store()
        store.add_order(
            {
                "order_id": order_id or execution_trace_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "quantity": qty,
                "price": exit_price or entry_price,
                "filled_price": exit_price or entry_price,
                "pnl": pnl or 0.0,
                "pnl_percent": pnl_percent or 0.0,
                "status": status,
                "filled_at": filled_at or datetime.now(timezone.utc).isoformat(),
                "trace_id": execution_trace_id,
            }
        )
        store.upsert_trade_fill(
            {
                "id": execution_trace_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "order_id": order_id,
                "execution_trace_id": execution_trace_id,
                "signal_trace_id": signal_trace_id,
                "grade": grade,
                "grade_score": grade_score,
                "grade_label": grade_label,
                "status": status,
                "filled_at": filled_at or datetime.now(timezone.utc).isoformat(),
                "graded_at": graded_at,
                "reflected_at": reflected_at,
            }
        )
        return

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
                        :schema_version, :source, NOW(), NOW()
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
                    "source": SOURCE_EXECUTION,
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
