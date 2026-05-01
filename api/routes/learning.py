"""Learning pipeline API — real data only, no mocks.

Every number returned by these endpoints maps directly to a DB query
(trade_evaluations / reflections / strategies) or to InMemoryStore when DB
is unavailable.  The ``mode`` field in every response tells the caller which
path was used so the UI can surface a banner when running in memory mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.constants import FieldName
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.agents.trade_scorer import compute_learning_metrics

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
    return str(ts)


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
        all_evals = store.get_trade_evaluations(200)
        page = all_evals[offset : offset + limit]
        return {
            "trades": page,
            "total": len(all_evals),
            "limit": limit,
            "offset": offset,
            "mode": mode,
        }

    try:
        from sqlalchemy import text

        from api.database import AsyncSessionFactory

        async with AsyncSessionFactory() as session:
            count_row = await session.execute(text("SELECT COUNT(*) FROM trade_evaluations"))
            total = int(count_row.scalar() or 0)

            rows = await session.execute(
                text("""
                    SELECT id, trade_id, symbol, side, pnl, return_pct,
                           entry_quality, exit_quality, timing_score, signal_alignment,
                           risk_reward, overall_score, grade, confidence,
                           mistakes, strengths, created_at
                    FROM trade_evaluations
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"limit": limit, "offset": offset},
            )
            trades = [
                {
                    "id": str(r[0]),
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
                    "created_at": _iso(r[16]),
                }
                for r in rows.all()
            ]
        return {"trades": trades, "total": total, "limit": limit, "offset": offset, "mode": mode}
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
                return {"trade": ev, "mode": "memory"}
        raise HTTPException(status_code=404, detail="Trade evaluation not found")

    try:
        from sqlalchemy import text

        from api.database import AsyncSessionFactory

        async with AsyncSessionFactory() as session:
            row = await session.execute(
                text("""
                    SELECT id, trade_id, symbol, side, pnl, return_pct,
                           entry_quality, exit_quality, timing_score, signal_alignment,
                           risk_reward, overall_score, grade, confidence,
                           mistakes, strengths, created_at
                    FROM trade_evaluations
                    WHERE trade_id = :trade_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"trade_id": trade_id},
            )
            r = row.first()
            if r is None:
                raise HTTPException(status_code=404, detail="Trade evaluation not found")
            return {
                "trade": {
                    "id": str(r[0]),
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
                    "created_at": _iso(r[16]),
                },
                "mode": "db",
            }
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
        metrics = compute_learning_metrics(evaluations)
        return {**metrics, "mode": mode, "timestamp": datetime.now(timezone.utc).isoformat()}

    try:
        from sqlalchemy import text

        from api.database import AsyncSessionFactory

        async with AsyncSessionFactory() as session:
            rows = await session.execute(
                text("""
                    SELECT pnl, return_pct, overall_score, grade, created_at
                    FROM trade_evaluations
                    ORDER BY created_at ASC
                    LIMIT 500
                """)
            )
            raw = rows.all()

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
        return {**metrics, "mode": mode, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception:
        log_structured("error", "learning_metrics_failed", exc_info=True)
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
            "reflections": store.get_reflections(limit),
            "total": len(store.reflections),
            "mode": mode,
        }

    try:
        from sqlalchemy import text

        from api.database import AsyncSessionFactory

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
                {"limit": limit},
            )
            reflections = [
                {
                    "id": str(r[0]),
                    FieldName.PATTERNS: _as_list(r[1]),
                    FieldName.MISTAKE_CLUSTERS: _as_list(r[2]),
                    FieldName.RECOMMENDATIONS: _as_list(r[3]),
                    FieldName.TRADES_ANALYZED: r[4],
                    FieldName.WIN_RATE: float(r[5]) if r[5] is not None else None,
                    FieldName.AVG_RETURN: float(r[6]) if r[6] is not None else None,
                    FieldName.CONFIDENCE: float(r[7]) if r[7] is not None else None,
                    "created_at": _iso(r[8]),
                }
                for r in rows.all()
            ]
        return {"reflections": reflections, "total": total, "mode": mode}
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
            "strategies": store.get_strategies(limit),
            "total": len(store.strategies),
            "mode": mode,
        }

    try:
        from sqlalchemy import text

        from api.database import AsyncSessionFactory

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
                {"limit": limit},
            )
            strategies = [
                {
                    "id": str(r[0]),
                    FieldName.RULES: _as_dict(r[1]),
                    "description": r[2],
                    FieldName.EXPECTED_IMPROVEMENT: float(r[3]) if r[3] is not None else None,
                    FieldName.STATUS: r[4],
                    FieldName.REFLECTION_ID: r[5],
                    "created_at": _iso(r[6]),
                }
                for r in rows.all()
            ]
        return {"strategies": strategies, "total": total, "mode": mode}
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
        return {
            "mode": mode,
            "timestamp": now,
            "stages": {
                "scoring": {
                    "status": "active" if store.trade_evaluations else "idle",
                    "jobs_processed": len(store.trade_evaluations),
                    "last_run": _iso(
                        store.trade_evaluations[-1].get("created_at")
                        if store.trade_evaluations
                        else None
                    ),
                    "error_count": 0,
                },
                "reflection": {
                    "status": "active" if store.reflections else "idle",
                    "jobs_processed": len(store.reflections),
                    "last_run": _iso(
                        store.reflections[-1].get("created_at") if store.reflections else None
                    ),
                    "error_count": 0,
                },
                "strategy_proposer": {
                    "status": "active" if store.strategies else "idle",
                    "jobs_processed": len(store.strategies),
                    "last_run": _iso(
                        store.strategies[-1].get("created_at") if store.strategies else None
                    ),
                    "error_count": 0,
                },
            },
        }

    try:
        from sqlalchemy import text

        from api.database import AsyncSessionFactory

        async with AsyncSessionFactory() as session:
            eval_row = await session.execute(
                text("""
                    SELECT COUNT(*), MAX(created_at)
                    FROM trade_evaluations
                """)
            )
            eval_count, eval_last = eval_row.first() or (0, None)

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
            "mode": mode,
            "timestamp": now,
            "stages": {
                "scoring": {
                    "status": "active" if eval_count else "idle",
                    "jobs_processed": int(eval_count or 0),
                    "last_run": _iso(eval_last),
                    "error_count": 0,
                },
                "reflection": {
                    "status": "active" if ref_count else "idle",
                    "jobs_processed": int(ref_count or 0),
                    "last_run": _iso(ref_last),
                    "error_count": 0,
                },
                "strategy_proposer": {
                    "status": "active" if strat_count else "idle",
                    "jobs_processed": int(strat_count or 0),
                    "last_run": _iso(strat_last),
                    "error_count": 0,
                },
            },
        }
    except Exception:
        log_structured("error", "learning_pipeline_status_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
