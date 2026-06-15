"""Serialization and row-mapping helpers for the learning API.

Pure-ish presentation logic split out of ``api/routes/learning.py`` so the
route handlers stay focused on HTTP + SQL orchestration. These helpers take
their session/store/text dependencies as arguments (no module-level DB state),
which keeps them trivially unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import FieldName, GradeType
from api.utils import safe_json_loads


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return safe_json_loads(value, default={})
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return safe_json_loads(value, default=[])
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


def _mem_trade_eval(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize an InMemoryStore trade_evaluation to the DB response shape.

    ``score_trade`` (the producer) sets ``trade_eval_id`` but no ``id``, while the
    DB path's ``_row_to_trade_eval`` always emits ``id``. Backfill it so memory-mode
    list/detail responses match DB mode — the UI keys and links rows on ``id``.
    """
    out = dict(entry)
    if not out.get(FieldName.ID):
        out[FieldName.ID] = str(entry.get(FieldName.TRADE_EVAL_ID) or "")
    return out


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
        raw = float(g.get(FieldName.SCORE) or g.get(FieldName.SCORE_PCT) or 0)
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
