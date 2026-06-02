import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from api.constants import (
    ALL_AGENT_NAMES,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    SOURCE_SIGNAL,
    FieldName,
    LogType,
    OrderStatus,
    ProposalStatus,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.dashboard.utils import _as_dict, _timestamp_to_iso


def _in_memory_reflections(limit: int = 20) -> list[dict[str, Any]]:
    """Return reflection logs from memory in the learning endpoint shape."""
    safe_limit = max(1, min(limit, 200))
    rows = [
        row
        for row in reversed(
            get_runtime_store().agent_logs[-200:] + get_runtime_store().event_history[-200:]
        )
        if row.get(FieldName.LOG_TYPE) == LogType.REFLECTION
    ][:safe_limit]
    reflections = []
    for row in rows:
        payload = _as_dict(row.get(FieldName.PAYLOAD))
        timestamp = _timestamp_to_iso(
            row.get(FieldName.CREATED_AT)
            or row.get(FieldName.TIMESTAMP)
            or payload.get(FieldName.TIMESTAMP)
        )
        reflections.append(
            {
                "trace_id": row.get(FieldName.TRACE_ID) or payload.get(FieldName.TRACE_ID),
                "summary": payload.get(FieldName.SUMMARY, ""),
                FieldName.HYPOTHESES: payload.get(FieldName.HYPOTHESES, []),
                FieldName.WINNING_FACTORS: payload.get(FieldName.WINNING_FACTORS, []),
                FieldName.LOSING_FACTORS: payload.get(FieldName.LOSING_FACTORS, []),
                FieldName.REGIME_EDGE: payload.get(FieldName.REGIME_EDGE, {}),
                FieldName.FILLS_ANALYZED: payload.get(FieldName.FILLS_ANALYZED),
                "timestamp": timestamp,
            }
        )
    return reflections


async def get_grade_history_payload(limit: int) -> dict[str, Any]:
    """Get recent agent grade history from agent_grades table and agent_logs."""
    if not is_db_available():
        store = get_runtime_store()
        grades = store.get_grades(limit=limit)
        return {
            FieldName.GRADES: grades,
            FieldName.TOTAL: len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.GRADE, FieldName.LIMIT: limit},
            )
            rows = result.all()
        grades = []
        for row in rows:
            payload = _as_dict(row[1])
            grades.append(
                {
                    "trace_id": row[0],
                    "grade": payload.get(FieldName.GRADE),
                    "score": payload.get(FieldName.SCORE),
                    "score_pct": payload.get(FieldName.SCORE_PCT),
                    "metrics": payload.get(FieldName.METRICS, {}),
                    "self_correction": payload.get(FieldName.SELF_CORRECTION, {}),
                    FieldName.FILLS_GRADED: payload.get(FieldName.FILLS_GRADED),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
            )

        # Backward compatibility: older deployments only write agent_grades rows.
        if not grades:
            async with AsyncSessionFactory() as session:
                fallback_result = await session.execute(
                    text("""
                        SELECT trace_id, score, metrics, created_at
                        FROM agent_grades
                        WHERE source IS DISTINCT FROM :signal_source
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: limit, "signal_source": SOURCE_SIGNAL},
                )
                for row in fallback_result.all():
                    metrics = _as_dict(row[2])
                    score = float(row[1]) if row[1] is not None else None
                    grades.append(
                        {
                            "trace_id": row[0],
                            "grade": None,
                            "score": score,
                            "score_pct": round(score, 2) if score is not None else None,
                            "metrics": metrics,
                            "self_correction": metrics.get(FieldName.SELF_CORRECTION, {}),
                            FieldName.FILLS_GRADED: metrics.get(FieldName.FILLS_GRADED),
                            "timestamp": row[3].isoformat() if row[3] else None,
                        }
                    )
        return {
            FieldName.GRADES: grades,
            FieldName.TOTAL: len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "grades fetch failed", exc_info=True)
        if is_db_available():
            raise HTTPException(status_code=500, detail="Internal server error") from None
        store = get_runtime_store()
        grades = store.get_grades(limit=limit)
        return {
            FieldName.GRADES: grades,
            FieldName.TOTAL: len(grades),
            "error": "grades_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def get_ic_weights_payload() -> dict[str, Any]:
    """Get current IC factor weights from Redis."""
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(REDIS_KEY_IC_WEIGHTS)
        weights = json.loads(raw) if raw else {}
        history_result: list[dict[str, Any]] = []
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT factor_name, ic_score, computed_at
                            FROM factor_ic_history
                            ORDER BY computed_at DESC
                            LIMIT 20
                        """)
                    )
                    rows = result.all()
                    history_result = [
                        {
                            FieldName.FACTOR: row[0],
                            FieldName.IC_SCORE: float(row[1]),
                            FieldName.COMPUTED_AT: row[2].isoformat() if row[2] else None,
                        }
                        for row in rows
                    ]
            except Exception:
                pass
        return {
            FieldName.CURRENT_WEIGHTS: weights,
            FieldName.HISTORY: history_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "redis_cache" if is_db_available() else "in_memory",
        }
    except Exception:
        log_structured("error", "ic weights fetch failed", exc_info=True)
        return {
            FieldName.CURRENT_WEIGHTS: {},
            FieldName.HISTORY: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_reflections_payload(limit: int) -> dict[str, Any]:
    """Get recent reflection outputs from agent_logs."""
    if not is_db_available():
        reflections = _in_memory_reflections(limit=limit)
        return {
            FieldName.REFLECTIONS: reflections,
            FieldName.TOTAL: len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.REFLECTION, FieldName.LIMIT: limit},
            )
            rows = result.all()
        reflections = [
            {
                "trace_id": row[0],
                "summary": _as_dict(row[1]).get(FieldName.SUMMARY, ""),
                FieldName.HYPOTHESES: _as_dict(row[1]).get(FieldName.HYPOTHESES, []),
                FieldName.WINNING_FACTORS: _as_dict(row[1]).get(FieldName.WINNING_FACTORS, []),
                FieldName.LOSING_FACTORS: _as_dict(row[1]).get(FieldName.LOSING_FACTORS, []),
                FieldName.REGIME_EDGE: _as_dict(row[1]).get(FieldName.REGIME_EDGE, {}),
                FieldName.FILLS_ANALYZED: _as_dict(row[1]).get(FieldName.FILLS_ANALYZED),
                "timestamp": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
        return {
            FieldName.REFLECTIONS: reflections,
            FieldName.TOTAL: len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "reflections fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def get_learning_loop_payload() -> dict[str, Any]:
    """Snapshot of the learning-loop control plane.

    Returns: latest grade, recent proposals (with applied_at if ProposalApplier
    has acted on them), per-symbol x signal-type loss attribution, and the
    current Redis control-plane state (trading_paused, signal_weight_scale,
    suspended agents). The frontend "Learning Loop" panel renders this.
    """
    out: dict[str, Any] = {
        FieldName.LATEST_GRADE: None,
        FieldName.RECENT_PROPOSALS: [],
        FieldName.LOSS_ATTRIBUTION: [],
        FieldName.CONTROL_PLANE: {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Control-plane Redis keys (best-effort — Redis must be reachable
    # but missing keys are not errors, they just mean "not set yet").
    try:
        redis_client = await get_redis()
        paused_raw = await redis_client.get(REDIS_KEY_TRADING_PAUSED)
        paused_reason = await redis_client.get(REDIS_KEY_TRADING_PAUSED_REASON)
        weight_scale_raw = await redis_client.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE)
        try:
            weight_scale = float(weight_scale_raw) if weight_scale_raw is not None else 1.0
        except (TypeError, ValueError):
            weight_scale = 1.0
        suspended: list[dict[str, Any]] = []
        for name in ALL_AGENT_NAMES:
            until_raw = await redis_client.get(REDIS_KEY_AGENT_SUSPENDED.format(name=name))
            if until_raw:
                try:
                    suspended.append({"agent_name": name, "suspended_until": float(until_raw)})
                except (TypeError, ValueError):
                    suspended.append({"agent_name": name, "suspended_until": None})
        out[FieldName.CONTROL_PLANE] = {
            FieldName.TRADING_PAUSED: paused_raw == "1",
            FieldName.TRADING_PAUSED_REASON: paused_reason,
            FieldName.SIGNAL_WEIGHT_SCALE: round(weight_scale, 6),
            FieldName.SUSPENDED_AGENTS: suspended,
        }
    except Exception:
        log_structured("warning", "learning_loop_control_plane_read_failed", exc_info=True)

    if not is_db_available():
        # Memory-mode fallback: pull latest grade + proposals from InMemoryStore.
        store = get_runtime_store()
        grades = store.get_grades(limit=1)
        if grades:
            g = grades[0]
            out[FieldName.LATEST_GRADE] = {
                FieldName.TRACE_ID: g.get(FieldName.TRACE_ID),
                FieldName.GRADE: g.get(FieldName.GRADE),
                FieldName.SCORE_PCT: g.get(FieldName.SCORE_PCT),
                FieldName.METRICS: g.get(FieldName.METRICS, {}),
                FieldName.SELF_CORRECTION: g.get(FieldName.SELF_CORRECTION, {}),
                FieldName.FILLS_GRADED: g.get(FieldName.FILLS_GRADED),
                FieldName.TIMESTAMP: g.get(FieldName.TIMESTAMP),
            }
        try:
            from api.services.dashboard.proposals import _in_memory_proposals  # noqa: PLC0415

            raw_proposals = _in_memory_proposals(limit=20)
            out[FieldName.RECENT_PROPOSALS] = [
                {
                    FieldName.TRACE_ID: p.get(FieldName.TRACE_ID),
                    FieldName.PROPOSAL_TYPE: p.get(FieldName.PROPOSAL_TYPE),
                    FieldName.ACTION: p.get(FieldName.ACTION),
                    FieldName.APPLIED: bool(p.get(FieldName.APPLIED, False)),
                    FieldName.APPLIED_AT: p.get(FieldName.APPLIED_AT),
                    FieldName.APPLIED_BY: p.get(FieldName.APPLIED_BY),
                    FieldName.MESSAGE: p.get(FieldName.MESSAGE),
                    FieldName.TIMESTAMP: p.get(FieldName.CREATED_AT),
                }
                for p in raw_proposals
            ]
        except Exception:
            log_structured("warning", "learning_loop_memory_proposals_failed", exc_info=True)
        return out

    # 2. Latest grade — newest agent_logs row with log_type=LogType.GRADE.
    try:
        async with AsyncSessionFactory() as session:
            grade_row = await session.execute(
                text(
                    """
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"log_type": LogType.GRADE},
            )
            row = grade_row.first()
            if row is not None:
                payload = _as_dict(row[1])
                out[FieldName.LATEST_GRADE] = {
                    "trace_id": row[0],
                    "grade": payload.get(FieldName.GRADE),
                    "score_pct": payload.get(FieldName.SCORE_PCT),
                    "metrics": payload.get(FieldName.METRICS, {}),
                    "self_correction": payload.get(FieldName.SELF_CORRECTION, {}),
                    FieldName.FILLS_GRADED: payload.get(FieldName.FILLS_GRADED),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
    except Exception:
        log_structured("warning", "learning_loop_latest_grade_failed", exc_info=True)

    # 3. Recent proposals with applied_at — ProposalApplier writes a
    # log_type=LogType.PROPOSAL row with FieldName.APPLIED_AT after each apply,
    # so a proposal is "pending" iff no log row exists with the same
    # trace_id and applied=true.
    try:
        async with AsyncSessionFactory() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT 20
                    """
                ),
                {"log_type": LogType.PROPOSAL},
            )
            proposals = []
            for row in rows.all():
                payload = _as_dict(row[1])
                proposals.append(
                    {
                        "trace_id": row[0],
                        "proposal_type": payload.get(FieldName.PROPOSAL_TYPE),
                        "action": payload.get(FieldName.ACTION),
                        "applied": bool(payload.get(FieldName.APPLIED, False)),
                        "applied_at": payload.get(FieldName.APPLIED_AT),
                        "applied_by": payload.get(FieldName.APPLIED_BY),
                        "message": payload.get(FieldName.MESSAGE),
                        "timestamp": row[2].isoformat() if row[2] else None,
                    }
                )
            out[FieldName.RECENT_PROPOSALS] = proposals
    except Exception:
        log_structured("warning", "learning_loop_proposals_failed", exc_info=True)

    # 4. Loss attribution — group closed trades by symbol x signal_type.
    # We pull the signal_type from agent_runs (joined by trace_id) so we
    # can show "every momentum_buy on BTC after threshold X loses".
    try:
        async with AsyncSessionFactory() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT
                        o.symbol AS symbol,
                        COALESCE(ar.signal_data::jsonb->>'signal_type', 'unknown') AS signal_type,
                        COUNT(*) AS trades,
                        COUNT(*) FILTER (WHERE COALESCE(tl.pnl, 0) < 0) AS losses,
                        COALESCE(SUM(tl.pnl), 0)::float AS total_pnl,
                        COALESCE(AVG(tl.pnl), 0)::float AS avg_pnl
                    FROM trade_lifecycle tl
                    JOIN orders o ON o.id::text = tl.order_id
                    LEFT JOIN agent_runs ar ON ar.trace_id = tl.execution_trace_id
                    WHERE tl.pnl IS NOT NULL
                    GROUP BY o.symbol, signal_type
                    ORDER BY total_pnl ASC
                    LIMIT 30
                    """
                )
            )
            attribution = []
            for row in rows.all():
                attribution.append(
                    {
                        "symbol": row[0],
                        "signal_type": row[1],
                        FieldName.TRADES: int(row[2] or 0),
                        FieldName.LOSSES: int(row[3] or 0),
                        FieldName.TOTAL_PNL: round(float(row[4] or 0.0), 2),
                        FieldName.AVG_PNL: round(float(row[5] or 0.0), 4),
                    }
                )
            out[FieldName.LOSS_ATTRIBUTION] = attribution
    except Exception:
        log_structured("warning", "learning_loop_loss_attribution_failed", exc_info=True)

    return out


async def get_learning_proposals_payload(limit: int) -> dict[str, Any]:
    """Get recent strategy proposals from agent_logs."""
    from api.services.dashboard.proposals import _in_memory_proposals  # noqa: PLC0415

    if not is_db_available():
        proposals = _in_memory_proposals(limit=limit)
        return {
            FieldName.PROPOSALS: proposals,
            FieldName.TOTAL: len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.PROPOSAL, FieldName.LIMIT: limit},
            )
            rows = result.all()
        proposals = []
        for row in rows:
            payload = _as_dict(row[1])
            proposals.append(
                {
                    FieldName.ID: row[0],
                    "proposal_type": payload.get(FieldName.PROPOSAL_TYPE, "parameter_change"),
                    "content": payload.get(FieldName.CONTENT, {}),
                    "requires_approval": payload.get(FieldName.REQUIRES_APPROVAL, True),
                    "confidence": payload.get(FieldName.CONFIDENCE),
                    "reflection_trace_id": payload.get(FieldName.REFLECTION_TRACE_ID),
                    "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
            )

        if not proposals:
            try:
                async with AsyncSessionFactory() as session:
                    fallback_result = await session.execute(
                        text("""
                            SELECT
                                e.id,
                                COALESCE(
                                    to_jsonb(e)->'data',
                                    to_jsonb(e)->'payload',
                                    '{}'::jsonb
                                ) AS payload,
                                e.created_at
                            FROM events e
                            WHERE event_type = 'strategy.proposal'
                            ORDER BY created_at DESC
                            LIMIT :limit
                        """),
                        {FieldName.LIMIT: limit},
                    )
                    for row in fallback_result.all():
                        data = _as_dict(row[1])
                        proposals.append(
                            {
                                FieldName.ID: str(row[0]),
                                "proposal_type": data.get(
                                    FieldName.PROPOSAL_TYPE, "strategy_proposal"
                                ),
                                "content": data,
                                "requires_approval": True,
                                "confidence": data.get(FieldName.CONFIDENCE),
                                "reflection_trace_id": data.get(FieldName.TRACE_ID),
                                "status": data.get(FieldName.STATUS, OrderStatus.PENDING),
                                "timestamp": row[2].isoformat() if row[2] else None,
                            }
                        )
            except Exception:
                log_structured(
                    "warning",
                    "learning proposals events fallback unavailable",
                    exc_info=True,
                )
        return {
            FieldName.PROPOSALS: proposals,
            FieldName.TOTAL: len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        return {
            FieldName.PROPOSALS: [],
            FieldName.TOTAL: 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def update_proposal_status_payload(trace_id: str, status: str) -> dict[str, Any]:
    """Persist proposal approval or rejection back to agent_logs payload."""
    from api.services.dashboard.proposals import _update_in_memory_proposal_status  # noqa: PLC0415

    if status not in {ProposalStatus.APPROVED, ProposalStatus.REJECTED}:
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")
    if not is_db_available():
        if not _update_in_memory_proposal_status(trace_id, status):
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    UPDATE agent_logs
                    SET payload = (payload::jsonb || jsonb_build_object('status', :status::text))::text
                    WHERE trace_id = :trace_id AND log_type = :log_type
                    RETURNING trace_id
                """),
                {"trace_id": trace_id, "status": status, "log_type": LogType.PROPOSAL},
            )
            updated = result.fetchone()
            await session.commit()
        if updated is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal_status_update_failed", trace_id=trace_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
