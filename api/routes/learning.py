"""Learning pipeline API — two operating modes, no mocks.

DB UP   (is_db_available() == True):  queries hit PostgreSQL tables
        trade_evaluations / reflections / strategies.
        If trade_evaluations is still empty (migration ran but no
        STREAM_TRADE_COMPLETED events processed yet), agent_grades is
        bridged into the same response shape so the UI always has data.

DB DOWN (is_db_available() == False): reads come from InMemoryStore,
        which agents write to instead of Postgres while the DB is
        unavailable.  InMemoryStore is the authoritative state in this
        mode — not a fallback.  If no trade_evaluations have been written
        yet (GradeAgent ran but no STREAM_TRADE_COMPLETED events were
        processed), grade_history is bridged to fill the trades list.

The ``mode`` field in every response ("db" or "memory") tells the UI
which path was used so it can surface an appropriate banner.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from api.constants import FieldName, GradeType
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.agents.trade_scorer import (
    aggregate_model_performance,
    compute_learning_metrics,
)

router = APIRouter(prefix="/learning", tags=["learning"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _iso(ts: Any) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        # InMemoryStore defaults to time.time() (Unix epoch float)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    return str(ts)


def _grade_from_score(score: float) -> str:
    if score >= 0.90:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.60:
        return "C"
    if score >= 0.40:
        return "D"
    return "F"


async def _trade_eval_has_provenance(session: Any) -> bool:
    """True when trade_evaluations has the model_used column (migration 20260502).

    Lets the trade endpoints tolerate a partial-migration window: if the
    provenance columns aren't present yet, callers fall back to the base SELECT
    instead of 500-ing on a missing column.
    """
    try:
        chk = await session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'trade_evaluations' "
                "AND column_name = 'model_used' LIMIT 1"
            )
        )
        return chk.first() is not None
    except Exception:
        return False


# Column order for trade_evaluations SELECTs. Fixed identifiers (never user
# input) so they are safe to interpolate into text(). _row_to_trade_eval reads
# rows positionally and MUST stay in sync with this order.
_TRADE_EVAL_COLS = (
    "id, trade_id, symbol, side, pnl, return_pct, "
    "entry_quality, exit_quality, timing_score, signal_alignment, "
    "risk_reward, overall_score, grade, confidence, "
    "mistakes, strengths, created_at"
)
_TRADE_EVAL_COLS_PROV = _TRADE_EVAL_COLS + ", model_used, primary_edge, decision_cost_usd"


def _row_to_trade_eval(r: Any, has_provenance: bool) -> dict[str, Any]:
    """Map one trade_evaluations row (ordered per _TRADE_EVAL_COLS) to the API
    trade shape. Shared by the list and single-trade endpoints so the response
    shape can't drift. Provenance fields are blank when those columns are absent
    (partial-migration window)."""
    return {
        FieldName.ID: str(r[0]),
        FieldName.TRADE_EVAL_ID: str(r[1]),
        FieldName.SYMBOL: r[2],
        FieldName.SIDE: r[3],
        FieldName.PNL: float(r[4]) if r[4] is not None else None,
        FieldName.PNL_PERCENT: float(r[5]) if r[5] is not None else None,
        FieldName.ENTRY_QUALITY: float(r[6]) if r[6] is not None else None,
        FieldName.EXIT_QUALITY: float(r[7]) if r[7] is not None else None,
        FieldName.TIMING_SCORE: float(r[8]) if r[8] is not None else None,
        FieldName.SIGNAL_ALIGNMENT: float(r[9]) if r[9] is not None else None,
        FieldName.RISK_REWARD: float(r[10]) if r[10] is not None else None,
        FieldName.OVERALL_SCORE: float(r[11]) if r[11] is not None else None,
        FieldName.GRADE: r[12],
        FieldName.CONFIDENCE: float(r[13]) if r[13] is not None else None,
        FieldName.MISTAKES: _as_list(r[14]),
        FieldName.STRENGTHS: _as_list(r[15]),
        FieldName.CREATED_AT: _iso(r[16]),
        FieldName.MODEL_USED: (r[17] or "") if has_provenance else "",
        FieldName.PRIMARY_EDGE: (r[18] or "") if has_provenance else "",
        FieldName.DECISION_COST_USD: (
            (float(r[19]) if r[19] is not None else 0.0) if has_provenance else 0.0
        ),
    }


def _grade_record_to_trade(score: float | None, trade_id: str, created_at: Any) -> dict[str, Any]:
    """Convert a raw grade score into the trade_evaluation response shape."""
    return {
        FieldName.ID: trade_id,
        FieldName.TRADE_EVAL_ID: trade_id,
        FieldName.SYMBOL: None,
        FieldName.SIDE: None,
        FieldName.PNL: None,
        FieldName.PNL_PERCENT: None,
        FieldName.ENTRY_QUALITY: None,
        FieldName.EXIT_QUALITY: None,
        FieldName.TIMING_SCORE: None,
        FieldName.SIGNAL_ALIGNMENT: None,
        FieldName.RISK_REWARD: None,
        FieldName.OVERALL_SCORE: round(score, 4) if score is not None else None,
        FieldName.GRADE: _grade_from_score(score) if score is not None else None,
        FieldName.CONFIDENCE: None,
        FieldName.MISTAKES: [],
        FieldName.STRENGTHS: [],
        FieldName.CREATED_AT: _iso(created_at),
    }


def _mem_grades_as_trades(store: Any, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """DB-down path: project grade_history into trade_evaluation shape.

    Used when DB is down and InMemoryStore.trade_evaluations is empty —
    meaning GradeAgent has been scoring but no STREAM_TRADE_COMPLETED
    events have been processed through the learning pipeline yet.
    grade_history is the best available evidence of agent scoring activity.
    """
    # Access grade_history directly to respect the full 500-entry store limit.
    # get_grades() caps at 200, which under-reports total during extended DB outages.
    # Filter to overall/untyped grades only — SignalGenerator writes GradeType.ACCURACY
    # entries into the same store; including those would inflate totals and mix in
    # signal-scoring rows that are unrelated to trade evaluations.
    all_grades = [
        g
        for g in reversed(store.grade_history)
        if g.get(FieldName.GRADE_TYPE) in (None, GradeType.OVERALL)
    ]
    total = len(all_grades)
    page = all_grades[offset : offset + limit]
    trades = []
    for g in page:
        raw = float(g.get(FieldName.SCORE) or g.get(FieldName.SCORE_PCT, 0))
        # GradeAgent may write percentage scores (0–100); normalize to [0, 1]
        score = raw / 100.0 if raw > 1.0 else raw
        trades.append(
            _grade_record_to_trade(
                score=score,
                trade_id=str(g.get(FieldName.TRACE_ID) or ""),
                created_at=g.get(FieldName.TIMESTAMP),
            )
        )
    return trades, total


async def _db_grades_as_trades(
    session: Any, text: Any, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """DB-up bridge: project agent_grades rows into trade_evaluation shape.

    Used when DB is up but trade_evaluations is empty — the migration ran
    but no STREAM_TRADE_COMPLETED events have completed the learning loop
    yet.  agent_grades holds GradeAgent's aggregate scores which are the
    best available evidence until proper trade evaluations exist.
    """
    count_row = await session.execute(
        text("SELECT COUNT(*) FROM agent_grades WHERE grade_type = 'overall'")
    )
    total = int(count_row.scalar() or 0)
    if total == 0:
        return [], 0
    rows = await session.execute(
        text("""
            SELECT trace_id, score, created_at
            FROM agent_grades
            WHERE grade_type = 'overall'
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {FieldName.LIMIT: limit, FieldName.OFFSET: offset},
    )
    trades = []
    for r in rows.all():
        raw = float(r[1]) if r[1] is not None else None
        # agent_grades.score may be a percentage (0–100); normalize to [0, 1]
        score = (raw / 100.0 if raw > 1.0 else raw) if raw is not None else None
        trades.append(
            _grade_record_to_trade(
                score=score,
                trade_id=str(r[0] or ""),
                created_at=r[2],
            )
        )
    return trades, total


# ---------------------------------------------------------------------------
# GET /learning/trades
# ---------------------------------------------------------------------------


@router.get("/trades")
async def list_trade_evaluations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Return paginated list of scored trade evaluations."""
    mode = "db" if is_db_available() else "memory"

    if not is_db_available():
        store = get_runtime_store()
        # Access the full list directly — get_trade_evaluations() caps at 200
        all_evals = list(reversed(store.trade_evaluations))
        if all_evals:
            total = len(all_evals)
            page = all_evals[offset : offset + limit]
        else:
            # No trade_evaluations yet — bridge from grade_history with correct pagination
            page, total = _mem_grades_as_trades(store, limit, offset)
        return {
            FieldName.TRADES: page,
            FieldName.TOTAL: total,
            FieldName.LIMIT: limit,
            FieldName.OFFSET: offset,
            FieldName.MODE: mode,
        }

    try:
        async with AsyncSessionFactory() as session:
            # trade_evaluations is empty if no STREAM_TRADE_COMPLETED events have been
            # processed yet; bridge to agent_grades so the UI has real scoring data.
            total = 0
            table_ok = True
            try:
                count_row = await session.execute(text("SELECT COUNT(*) FROM trade_evaluations"))
                total = int(count_row.scalar() or 0)
            except Exception:
                table_ok = False

            if not table_ok or total == 0:
                trades, total = await _db_grades_as_trades(session, text, limit, offset)
                return {
                    FieldName.TRADES: trades,
                    FieldName.TOTAL: total,
                    FieldName.LIMIT: limit,
                    FieldName.OFFSET: offset,
                    FieldName.MODE: mode,
                }

            # Provenance columns (model_used/primary_edge) were added in migration
            # 20260502. Probe once, then pick the column set so a partial-migration
            # window (table present, columns absent) never 500s this endpoint.
            has_provenance = await _trade_eval_has_provenance(session)
            cols = _TRADE_EVAL_COLS_PROV if has_provenance else _TRADE_EVAL_COLS
            rows = await session.execute(
                text(
                    f"SELECT {cols} FROM trade_evaluations "
                    "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                {FieldName.LIMIT: limit, FieldName.OFFSET: offset},
            )
            trades = [_row_to_trade_eval(r, has_provenance) for r in rows.all()]
        return {
            FieldName.TRADES: trades,
            FieldName.TOTAL: total,
            FieldName.LIMIT: limit,
            FieldName.OFFSET: offset,
            FieldName.MODE: mode,
        }
    except Exception:
        log_structured("error", "learning_trades_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# GET /learning/trades/{trade_id}
# ---------------------------------------------------------------------------


@router.get("/trades/{trade_id}")
async def get_trade_evaluation(trade_id: str) -> dict[str, Any]:
    """Return full detail for a single trade evaluation."""
    if not is_db_available():
        store = get_runtime_store()
        for ev in reversed(store.trade_evaluations):
            if str(ev.get(FieldName.TRADE_EVAL_ID)) == trade_id:
                return {"trade": ev, FieldName.MODE: "memory"}
        # trade_evaluations empty — IDs may come from the grade_history bridge;
        # search the full list directly to avoid the 200-entry cap of _mem_grades_as_trades
        if not store.trade_evaluations:
            for g in reversed(store.grade_history):
                if g.get(FieldName.GRADE_TYPE) not in (None, GradeType.OVERALL):
                    continue
                if str(g.get(FieldName.TRACE_ID) or "") == trade_id:
                    raw = float(g.get(FieldName.SCORE) or g.get(FieldName.SCORE_PCT, 0))
                    score = raw / 100.0 if raw > 1.0 else raw
                    return {
                        "trade": _grade_record_to_trade(
                            score=score,
                            trade_id=trade_id,
                            created_at=g.get(FieldName.TIMESTAMP),
                        ),
                        FieldName.MODE: "memory",
                    }
        raise HTTPException(status_code=404, detail="Trade evaluation not found")

    try:
        async with AsyncSessionFactory() as session:
            # trade_evaluations may not exist during a partial migration; guard
            # each query independently so the agent_grades bridge always runs.
            # Probe for provenance columns so a partial migration (table present,
            # model_used absent) doesn't fail the SELECT.
            has_provenance = await _trade_eval_has_provenance(session)
            cols = _TRADE_EVAL_COLS_PROV if has_provenance else _TRADE_EVAL_COLS
            r = None
            te_accessible = True
            try:
                row = await session.execute(
                    text(
                        f"SELECT {cols} FROM trade_evaluations "
                        "WHERE trade_id = :trade_id ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"trade_id": trade_id},
                )
                r = row.first()
            except Exception:
                te_accessible = False
            if r is not None:
                return {"trade": _row_to_trade_eval(r, has_provenance), FieldName.MODE: "db"}
            # trade_evaluations miss or inaccessible — IDs may come from the agent_grades bridge
            te_empty = not te_accessible
            if te_accessible:
                try:
                    cnt = await session.execute(text("SELECT COUNT(*) FROM trade_evaluations"))
                    te_empty = int(cnt.scalar() or 0) == 0
                except Exception:
                    te_empty = True
            if te_empty:
                ag_row = await session.execute(
                    text("""
                        SELECT trace_id, score, created_at
                        FROM agent_grades
                        WHERE trace_id = :trade_id
                          AND grade_type = 'overall'
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"trade_id": trade_id},
                )
                ag_r = ag_row.first()
                if ag_r is not None:
                    raw = float(ag_r[1]) if ag_r[1] is not None else None
                    score = (raw / 100.0 if raw > 1.0 else raw) if raw is not None else None
                    trade = _grade_record_to_trade(
                        score=score,
                        trade_id=str(ag_r[0] or ""),
                        created_at=ag_r[2],
                    )
                    return {"trade": trade, FieldName.MODE: "db"}
            raise HTTPException(status_code=404, detail="Trade evaluation not found")
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "learning_trade_detail_failed", trade_id=trade_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# GET /learning/metrics
# ---------------------------------------------------------------------------


@router.get("/metrics")
async def get_learning_metrics() -> dict[str, Any]:
    """Aggregate agent performance metrics — the truth layer.

    win_rate, avg_return, sharpe, max_drawdown, avg_score, score_trend,
    consistency are all computed from real trade_evaluations rows.
    """
    mode = "db" if is_db_available() else "memory"

    if not is_db_available():
        store = get_runtime_store()
        evaluations = store.get_trade_evaluations(200)
        if not evaluations:
            # Grade-bridged records have pnl=None, making win_rate/avg_return/sharpe
            # all zero.  Synthesize PnL from overall_score — same as the DB-up bridge.
            # Filter to overall/untyped grades to exclude SignalGenerator accuracy entries.
            for g in store.grade_history:
                if g.get(FieldName.GRADE_TYPE) not in (None, GradeType.OVERALL):
                    continue
                raw = float(g.get(FieldName.SCORE) or g.get(FieldName.SCORE_PCT, 0))
                score_n = raw / 100.0 if raw > 1.0 else raw
                evaluations.append(
                    {
                        FieldName.PNL: score_n - 0.5,
                        FieldName.PNL_PERCENT: (score_n - 0.5) * 20,
                        FieldName.OVERALL_SCORE: score_n,
                    }
                )
        metrics = compute_learning_metrics(evaluations)
        return {
            **metrics,
            FieldName.MODE: mode,
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }

    try:
        async with AsyncSessionFactory() as session:
            # trade_evaluations is the primary source; bridge to agent_grades when
            # the table is empty (no trade completions have cycled through yet).
            raw = []
            try:
                rows = await session.execute(
                    text("""
                        SELECT pnl, return_pct, overall_score, grade, created_at
                        FROM trade_evaluations
                        ORDER BY created_at ASC
                        LIMIT 500
                    """)
                )
                raw = rows.all()
            except Exception:
                pass

            if not raw:
                ag_rows = await session.execute(
                    text("""
                        SELECT score, created_at
                        FROM agent_grades
                        WHERE grade_type = 'overall'
                        ORDER BY created_at ASC
                        LIMIT 500
                    """)
                )
                evaluations = []
                for r in ag_rows.all():
                    raw_s = float(r[0]) if r[0] is not None else 0.0
                    # agent_grades.score may be a percentage (0–100); normalize to [0, 1]
                    score_n = raw_s / 100.0 if raw_s > 1.0 else raw_s
                    evaluations.append(
                        {
                            FieldName.PNL: score_n - 0.5,
                            FieldName.PNL_PERCENT: (score_n - 0.5) * 20,
                            FieldName.OVERALL_SCORE: score_n,
                        }
                    )
            else:
                evaluations = [
                    {
                        FieldName.PNL: float(r[0]) if r[0] is not None else 0.0,
                        FieldName.PNL_PERCENT: float(r[1]) if r[1] is not None else 0.0,
                        FieldName.OVERALL_SCORE: float(r[2]) if r[2] is not None else 0.0,
                        FieldName.GRADE: r[3],
                    }
                    for r in raw
                ]

        metrics = compute_learning_metrics(evaluations)
        return {
            **metrics,
            FieldName.MODE: mode,
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "learning_metrics_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# GET /learning/model-performance
# ---------------------------------------------------------------------------


@router.get("/model-performance")
async def get_model_performance() -> dict[str, Any]:
    """Per-model trade performance grouped by the LLM that produced each trade.

    Powered by decision provenance (``model_used`` on each trade evaluation):
    win rate, average score, and PnL per ``provider:model``. Same aggregation
    runs for both DB and memory mode so the two never diverge.
    """
    mode = "db" if is_db_available() else "memory"

    if not is_db_available():
        store = get_runtime_store()
        models = aggregate_model_performance(store.get_trade_evaluations(200))
        return {FieldName.MODELS: models, FieldName.MODE: mode}

    try:
        async with AsyncSessionFactory() as session:
            # No provenance columns yet (pre-migration) → nothing to attribute.
            if not await _trade_eval_has_provenance(session):
                return {FieldName.MODELS: [], FieldName.MODE: mode}
            rows = await session.execute(
                text("""
                    SELECT model_used, overall_score, pnl, decision_cost_usd
                    FROM trade_evaluations
                    WHERE model_used IS NOT NULL AND model_used <> ''
                    ORDER BY created_at DESC
                    LIMIT 1000
                """)
            )
            evaluations = [
                {
                    FieldName.MODEL_USED: r[0],
                    FieldName.OVERALL_SCORE: float(r[1]) if r[1] is not None else None,
                    FieldName.PNL: float(r[2]) if r[2] is not None else None,
                    FieldName.DECISION_COST_USD: float(r[3]) if r[3] is not None else 0.0,
                }
                for r in rows.all()
            ]
        return {FieldName.MODELS: aggregate_model_performance(evaluations), FieldName.MODE: mode}
    except Exception:
        log_structured("error", "learning_model_performance_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# GET /learning/reflections
# ---------------------------------------------------------------------------


@router.get("/reflections")
async def list_reflections(
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Return latest reflection analyses."""
    mode = "db" if is_db_available() else "memory"

    if not is_db_available():
        store = get_runtime_store()
        return {
            FieldName.REFLECTIONS: store.get_reflections(limit),
            FieldName.TOTAL: len(store.reflections),
            FieldName.MODE: mode,
        }

    try:
        async with AsyncSessionFactory() as session:
            count_row = await session.execute(text("SELECT COUNT(*) FROM reflections"))
            total = int(count_row.scalar() or 0)

            rows = await session.execute(
                text("""
                    SELECT id, patterns, mistake_clusters, recommendations,
                           trades_analyzed, win_rate, avg_return, confidence, created_at
                    FROM reflections
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {FieldName.LIMIT: limit},
            )
            reflections = [
                {
                    FieldName.ID: str(r[0]),
                    FieldName.PATTERNS: _as_list(r[1]),
                    FieldName.MISTAKE_CLUSTERS: _as_list(r[2]),
                    FieldName.RECOMMENDATIONS: _as_list(r[3]),
                    FieldName.TRADES_ANALYZED: r[4],
                    FieldName.WIN_RATE: float(r[5]) if r[5] is not None else None,
                    FieldName.AVG_RETURN: float(r[6]) if r[6] is not None else None,
                    FieldName.CONFIDENCE: float(r[7]) if r[7] is not None else None,
                    FieldName.CREATED_AT: _iso(r[8]),
                }
                for r in rows.all()
            ]
        return {FieldName.REFLECTIONS: reflections, FieldName.TOTAL: total, FieldName.MODE: mode}
    except Exception:
        log_structured("error", "learning_reflections_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# GET /learning/strategies
# ---------------------------------------------------------------------------


@router.get("/strategies")
async def list_strategies(
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Return latest strategy proposals."""
    mode = "db" if is_db_available() else "memory"

    if not is_db_available():
        store = get_runtime_store()
        return {
            FieldName.STRATEGIES: store.get_strategies(limit),
            FieldName.TOTAL: len(store.strategies),
            FieldName.MODE: mode,
        }

    try:
        async with AsyncSessionFactory() as session:
            count_row = await session.execute(text("SELECT COUNT(*) FROM strategies"))
            total = int(count_row.scalar() or 0)

            rows = await session.execute(
                text("""
                    SELECT id, rules, description, expected_improvement, status,
                           reflection_id, created_at
                    FROM strategies
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {FieldName.LIMIT: limit},
            )
            strategies = [
                {
                    FieldName.ID: str(r[0]),
                    FieldName.RULES: _as_dict(r[1]),
                    FieldName.DESCRIPTION: r[2],
                    FieldName.EXPECTED_IMPROVEMENT: float(r[3]) if r[3] is not None else None,
                    FieldName.STATUS: r[4],
                    FieldName.REFLECTION_ID: r[5],
                    FieldName.CREATED_AT: _iso(r[6]),
                }
                for r in rows.all()
            ]
        return {FieldName.STRATEGIES: strategies, FieldName.TOTAL: total, FieldName.MODE: mode}
    except Exception:
        log_structured("error", "learning_strategies_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# GET /learning/pipeline-status
# ---------------------------------------------------------------------------


@router.get("/pipeline-status")
async def get_pipeline_status() -> dict[str, Any]:
    """Observable pipeline status — each stage's last-run time and counts."""
    mode = "db" if is_db_available() else "memory"
    now = datetime.now(timezone.utc).isoformat()

    if not is_db_available():
        store = get_runtime_store()
        overall_grades = [
            g
            for g in store.grade_history
            if g.get(FieldName.GRADE_TYPE) in (None, GradeType.OVERALL)
        ]
        scoring_source = store.trade_evaluations or overall_grades
        return {
            FieldName.MODE: mode,
            FieldName.TIMESTAMP: now,
            FieldName.STAGES: {
                FieldName.SCORING: {
                    FieldName.STATUS: "active" if scoring_source else "idle",
                    FieldName.JOBS_PROCESSED: len(scoring_source),
                    FieldName.LAST_RUN: _iso(
                        (
                            scoring_source[-1].get(FieldName.CREATED_AT)
                            or scoring_source[-1].get(FieldName.TIMESTAMP)
                        )
                        if scoring_source
                        else None
                    ),
                    FieldName.ERROR_COUNT: 0,
                },
                FieldName.REFLECTION: {
                    FieldName.STATUS: "active" if store.reflections else "idle",
                    FieldName.JOBS_PROCESSED: len(store.reflections),
                    FieldName.LAST_RUN: _iso(
                        store.reflections[-1].get(FieldName.CREATED_AT)
                        if store.reflections
                        else None
                    ),
                    FieldName.ERROR_COUNT: 0,
                },
                FieldName.STRATEGY_PROPOSER: {
                    FieldName.STATUS: "active" if store.strategies else "idle",
                    FieldName.JOBS_PROCESSED: len(store.strategies),
                    FieldName.LAST_RUN: _iso(
                        store.strategies[-1].get(FieldName.CREATED_AT) if store.strategies else None
                    ),
                    FieldName.ERROR_COUNT: 0,
                },
            },
        }

    try:
        async with AsyncSessionFactory() as session:
            eval_count, eval_last = 0, None
            try:
                eval_row = await session.execute(
                    text("SELECT COUNT(*), MAX(created_at) FROM trade_evaluations")
                )
                eval_count, eval_last = eval_row.first() or (0, None)
            except Exception:
                pass

            if not eval_count:
                # trade_evaluations still empty — use agent_grades count so the
                # scoring stage reflects GradeAgent activity that has already run.
                ag_row = await session.execute(
                    text(
                        "SELECT COUNT(*), MAX(created_at) FROM agent_grades"
                        " WHERE grade_type = 'overall'"
                    )
                )
                eval_count, eval_last = ag_row.first() or (0, None)

            ref_row = await session.execute(
                text("""
                    SELECT COUNT(*), MAX(created_at)
                    FROM reflections
                """)
            )
            ref_count, ref_last = ref_row.first() or (0, None)

            strat_row = await session.execute(
                text("""
                    SELECT COUNT(*), MAX(created_at)
                    FROM strategies
                """)
            )
            strat_count, strat_last = strat_row.first() or (0, None)

        return {
            FieldName.MODE: mode,
            FieldName.TIMESTAMP: now,
            FieldName.STAGES: {
                FieldName.SCORING: {
                    FieldName.STATUS: "active" if eval_count else "idle",
                    FieldName.JOBS_PROCESSED: int(eval_count or 0),
                    FieldName.LAST_RUN: _iso(eval_last),
                    FieldName.ERROR_COUNT: 0,
                },
                FieldName.REFLECTION: {
                    FieldName.STATUS: "active" if ref_count else "idle",
                    FieldName.JOBS_PROCESSED: int(ref_count or 0),
                    FieldName.LAST_RUN: _iso(ref_last),
                    FieldName.ERROR_COUNT: 0,
                },
                FieldName.STRATEGY_PROPOSER: {
                    FieldName.STATUS: "active" if strat_count else "idle",
                    FieldName.JOBS_PROCESSED: int(strat_count or 0),
                    FieldName.LAST_RUN: _iso(strat_last),
                    FieldName.ERROR_COUNT: 0,
                },
            },
        }
    except Exception:
        log_structured("error", "learning_pipeline_status_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
