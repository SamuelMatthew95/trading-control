"""Shared database write helpers used by multiple agent implementations.

DB routing:
  - is_db_available() is checked upfront in every public function.
  - DB mode: performs SQL writes via AsyncSessionFactory.
  - Memory mode: writes to InMemoryStore; no DB session opened at all.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import (
    SOURCE_DB_HELPERS,
    SOURCE_EXECUTION,
    FieldName,
    GradeType,
    LifecyclePhase,
    LogType,
)
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
                    FieldName.FILLS_GRADED: payload.get(FieldName.FILLS_GRADED),
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
                FieldName.ID: f"mem-{len(store.agent_logs) + 1}",
                "agent_name": payload.get(FieldName.SOURCE)
                or payload.get(FieldName.AGENT)
                or payload.get(FieldName.AGENT_NAME)
                or log_type,
                "message": message,
                FieldName.REASONING: payload.get(FieldName.REASONING) or message,
                "log_level": "info",
                "trace_id": trace_id,
                "log_type": log_type,
                "confidence": payload.get(FieldName.CONFIDENCE_SCORE)
                or payload.get(FieldName.CONFIDENCE),
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
    if not is_db_available():
        get_runtime_store().add_grade(
            {
                "trace_id": trace_id,
                "grade": None,
                "score": score_pct,
                "score_pct": round(score_pct, 2) if score_pct is not None else None,
                "metrics": metrics,
                FieldName.FILLS_GRADED: metrics.get(FieldName.FILLS_GRADED),
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
                {
                    "factor_name": factor,
                    FieldName.IC_SCORE: ic_score,
                    FieldName.COMPUTED_AT: computed_at,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "factor_ic_persist_failed", factor=factor, exc_info=True)


async def persist_proposal(proposal: dict[str, Any]) -> None:
    """Insert a proposal into agent_logs for dashboard query and audit trail.

    Memory mode: writes to InMemoryStore event_history.
    """
    trace_id = proposal.get(FieldName.REFLECTION_TRACE_ID) or proposal.get(FieldName.MSG_ID) or ""
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
                return json.loads(payload)
            return payload or {}
    except Exception:
        log_structured("error", "get_last_reflection_failed", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Learning pipeline persistence
# ---------------------------------------------------------------------------


async def persist_trade_evaluation(trade_eval: dict[str, Any]) -> None:
    """Insert a per-trade evaluation row.

    Memory mode: writes to InMemoryStore.trade_evaluations.
    DB mode: INSERT into trade_evaluations table (idempotent on trade_eval_id).
    """
    if not is_db_available():
        get_runtime_store().add_trade_evaluation(trade_eval)
        return
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO trade_evaluations (
                        id, trade_id, symbol, side,
                        pnl, return_pct,
                        entry_quality, exit_quality, timing_score, signal_alignment,
                        risk_reward, overall_score, grade, confidence,
                        mistakes, strengths,
                        source, schema_version
                    ) VALUES (
                        gen_random_uuid(), :trade_id, :symbol, :side,
                        :pnl, :return_pct,
                        :entry_quality, :exit_quality, :timing_score, :signal_alignment,
                        :risk_reward, :overall_score, :grade, :confidence,
                        CAST(:mistakes AS JSONB), CAST(:strengths AS JSONB),
                        :source, :schema_version
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "trade_id": str(trade_eval.get(FieldName.TRADE_EVAL_ID) or ""),
                    "symbol": trade_eval.get(FieldName.SYMBOL),
                    "side": trade_eval.get(FieldName.SIDE),
                    "pnl": trade_eval.get(FieldName.PNL),
                    FieldName.RETURN_PCT: trade_eval.get(FieldName.PNL_PERCENT),
                    "entry_quality": trade_eval.get(FieldName.ENTRY_QUALITY),
                    "exit_quality": trade_eval.get(FieldName.EXIT_QUALITY),
                    "timing_score": trade_eval.get(FieldName.TIMING_SCORE),
                    "signal_alignment": trade_eval.get(FieldName.SIGNAL_ALIGNMENT),
                    "risk_reward": trade_eval.get(FieldName.RISK_REWARD),
                    "overall_score": trade_eval.get(FieldName.OVERALL_SCORE),
                    "grade": trade_eval.get(FieldName.GRADE),
                    "confidence": trade_eval.get(FieldName.CONFIDENCE),
                    "mistakes": json.dumps(trade_eval.get(FieldName.MISTAKES) or []),
                    "strengths": json.dumps(trade_eval.get(FieldName.STRENGTHS) or []),
                    "source": SOURCE_DB_HELPERS,
                    "schema_version": DB_SCHEMA_VERSION,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "trade_evaluation_persist_failed", exc_info=True)
        # Fall back to memory so data is not lost
        get_runtime_store().add_trade_evaluation(trade_eval)


async def persist_reflection_record(reflection: dict[str, Any]) -> None:
    """Insert a reflection analysis row.

    Memory mode: writes to InMemoryStore.reflections.
    DB mode: INSERT into reflections table.
    """
    if not is_db_available():
        get_runtime_store().add_reflection(reflection)
        return
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO reflections (
                        id, patterns, mistake_clusters, recommendations,
                        trades_analyzed, win_rate, avg_return, confidence,
                        source, schema_version
                    ) VALUES (
                        gen_random_uuid(),
                        CAST(:patterns AS JSONB),
                        CAST(:mistake_clusters AS JSONB),
                        CAST(:recommendations AS JSONB),
                        :trades_analyzed, :win_rate, :avg_return, :confidence,
                        :source, :schema_version
                    )
                """),
                {
                    "patterns": json.dumps(reflection.get(FieldName.PATTERNS) or []),
                    "mistake_clusters": json.dumps(
                        reflection.get(FieldName.MISTAKE_CLUSTERS) or []
                    ),
                    "recommendations": json.dumps(reflection.get(FieldName.RECOMMENDATIONS) or []),
                    "trades_analyzed": reflection.get(FieldName.TRADES_ANALYZED),
                    "win_rate": reflection.get(FieldName.WIN_RATE),
                    "avg_return": reflection.get(FieldName.AVG_RETURN),
                    "confidence": reflection.get(FieldName.CONFIDENCE),
                    "source": SOURCE_DB_HELPERS,
                    "schema_version": DB_SCHEMA_VERSION,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "reflection_record_persist_failed", exc_info=True)
        get_runtime_store().add_reflection(reflection)


async def persist_strategy_record(strategy: dict[str, Any]) -> None:
    """Insert a strategy proposal row.

    Memory mode: writes to InMemoryStore.strategies.
    DB mode: INSERT into strategies table.
    """
    if not is_db_available():
        get_runtime_store().add_strategy(strategy)
        return
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("""
                    INSERT INTO strategies (
                        id, rules, description, expected_improvement, status,
                        reflection_id, source, schema_version
                    ) VALUES (
                        gen_random_uuid(),
                        CAST(:rules AS JSONB),
                        :description,
                        :expected_improvement,
                        :status,
                        :reflection_id,
                        :source, :schema_version
                    )
                """),
                {
                    "rules": json.dumps(strategy.get(FieldName.RULES) or {}),
                    "description": strategy.get(FieldName.DESCRIPTION),
                    "expected_improvement": strategy.get(FieldName.EXPECTED_IMPROVEMENT),
                    "status": strategy.get(FieldName.STATUS, "pending"),
                    "reflection_id": strategy.get(FieldName.REFLECTION_ID),
                    "source": SOURCE_DB_HELPERS,
                    "schema_version": DB_SCHEMA_VERSION,
                },
            )
            await session.commit()
    except Exception:
        log_structured("warning", "strategy_record_persist_failed", exc_info=True)
        get_runtime_store().add_strategy(strategy)


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
                result = await session.execute(
                    text("""
                        INSERT INTO agent_instances
                            (id, instance_key, pool_name, status, started_at, schema_version, metadata)
                        VALUES
                            (:id, :key, :pool, 'active', NOW(), :schema_version, CAST(:metadata AS JSONB))
                        ON CONFLICT (instance_key) DO UPDATE SET
                            status = 'active',
                            retired_at = NULL,
                            metadata = COALESCE(agent_instances.metadata, '{}'::jsonb) || EXCLUDED.metadata
                        RETURNING id
                    """),
                    {
                        FieldName.ID: instance_id,
                        FieldName.KEY: instance_key,
                        FieldName.POOL: pool_name,
                        "schema_version": DB_SCHEMA_VERSION,
                        "metadata": json.dumps(
                            {
                                "agent_name": pool_name,
                                "agent_id": pool_name,
                                FieldName.AGENT_TYPE: "service",
                                "session_id": os.getenv("SESSION_ID", "default"),
                                FieldName.ENVIRONMENT: os.getenv("ENVIRONMENT", "dev"),
                            }
                        ),
                    },
                )
                persisted_id = result.scalar()
                await session.commit()
            persisted_id_str = str(persisted_id or "")
            if len(persisted_id_str) == 36 and persisted_id_str.count("-") == 4:
                return persisted_id_str
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
                {FieldName.ID: instance_id},
            )
            await session.commit()
            await write_agent_lifecycle_event(
                pool_name="unknown",
                instance_id=instance_id,
                lifecycle_phase=LifecyclePhase.STOPPED,
            )
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
                {FieldName.ID: instance_id},
            )
            await session.commit()
    except Exception:
        pass  # Non-critical counter — never raise


async def write_agent_lifecycle_event(
    *,
    pool_name: str,
    instance_id: str,
    lifecycle_phase: LifecyclePhase,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist lifecycle transitions in agent_logs as canonical lifecycle rows."""
    payload = {
        "agent_name": pool_name,
        "agent_id": pool_name,
        FieldName.INSTANCE_ID: instance_id,
        FieldName.LIFECYCLE_EVENT: lifecycle_phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        FieldName.DETAILS: details or {},
    }
    await write_agent_log(
        trace_id=f"{pool_name}:{instance_id}:{lifecycle_phase}",
        log_type="lifecycle",
        payload=payload,
    )


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
    session_id: str | None = None,
) -> None:
    """Insert or update one row in trade_lifecycle keyed on execution_trace_id.

    Memory mode: stores a compact order record in InMemoryStore so the
    dashboard fallback snapshot can show real trade activity.
    """
    if not is_db_available():
        store = get_runtime_store()
        normalized_status = str(status or "filled").lower()
        should_store_order = normalized_status in {"filled", "executed"} and qty is not None
        if should_store_order:
            store.add_order(
                {
                    FieldName.ORDER_ID: order_id or execution_trace_id,
                    FieldName.SYMBOL: symbol,
                    FieldName.SIDE: side,
                    FieldName.QTY: qty,
                    FieldName.QUANTITY: qty,
                    FieldName.PRICE: exit_price or entry_price,
                    FieldName.FILLED_PRICE: exit_price or entry_price,
                    FieldName.PNL: pnl,
                    FieldName.PNL_PERCENT: pnl_percent,
                    FieldName.STATUS: normalized_status,
                    FieldName.FILLED_AT: filled_at or datetime.now(timezone.utc).isoformat(),
                    FieldName.TRACE_ID: execution_trace_id,
                    FieldName.SESSION_ID: session_id,
                }
            )
        store.upsert_trade_fill(
            {
                FieldName.ID: execution_trace_id,
                FieldName.SYMBOL: symbol,
                FieldName.SIDE: side,
                FieldName.QTY: qty,
                FieldName.ENTRY_PRICE: entry_price,
                FieldName.EXIT_PRICE: exit_price,
                FieldName.PNL: pnl,
                FieldName.PNL_PERCENT: pnl_percent,
                FieldName.ORDER_ID: order_id,
                FieldName.EXECUTION_TRACE_ID: execution_trace_id,
                FieldName.SIGNAL_TRACE_ID: signal_trace_id,
                FieldName.GRADE: grade,
                FieldName.GRADE_SCORE: grade_score,
                FieldName.GRADE_LABEL: grade_label,
                FieldName.STATUS: normalized_status,
                FieldName.FILLED_AT: filled_at or datetime.now(timezone.utc).isoformat(),
                FieldName.GRADED_AT: graded_at,
                FieldName.REFLECTED_AT: reflected_at,
                FieldName.SESSION_ID: session_id,
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
                    FieldName.SYMBOL: symbol,
                    FieldName.SIDE: side.lower(),
                    FieldName.QTY: qty,
                    FieldName.ENTRY_PRICE: entry_price,
                    FieldName.EXIT_PRICE: exit_price,
                    FieldName.PNL: pnl,
                    FieldName.PNL_PERCENT: pnl_percent,
                    FieldName.ORDER_ID: order_id,
                    FieldName.SIGNAL_TRACE_ID: signal_trace_id,
                    FieldName.DECISION_TRACE_ID: decision_trace_id,
                    FieldName.EXECUTION_TRACE_ID: execution_trace_id,
                    FieldName.GRADE_TRACE_ID: grade_trace_id,
                    FieldName.REFLECTION_TRACE_ID: reflection_trace_id,
                    FieldName.GRADE: grade,
                    FieldName.GRADE_SCORE: grade_score,
                    FieldName.GRADE_LABEL: grade_label,
                    FieldName.STATUS: status,
                    FieldName.FILLED_AT: filled_at or now_iso,
                    FieldName.GRADED_AT: graded_at,
                    FieldName.REFLECTED_AT: reflected_at,
                    FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
                    FieldName.SOURCE: SOURCE_EXECUTION,
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
