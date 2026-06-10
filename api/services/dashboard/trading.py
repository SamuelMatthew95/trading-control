import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import (
    AGENT_EXECUTION,
    REDIS_AGENT_STATUS_KEY,
    STREAM_DECISIONS,
    STREAM_SIGNALS,
    FieldName,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available

# String tokens that mean "this number is legitimately absent" rather than
# "this number is malformed". An open position has no exit price or P&L yet, so
# these must be treated as missing — NOT reported as a degraded/sanitized field.
_NULL_LIKE_NUMERIC_TOKENS = frozenset(
    {"", "null", "none", "nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
)


def _is_null_like_numeric(value: Any) -> bool:
    """True when ``value`` means 'no number here', not 'a malformed number'.

    Distinguishes a legitimately-absent value (``None``, ``""``, ``"null"``,
    non-finite float) from genuine garbage (``"abc"``) so the caller can tell an
    open position's empty exit/P&L apart from a corrupt payload.
    """
    if value is None:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, str):
        return value.strip().lower() in _NULL_LIKE_NUMERIC_TOKENS
    return False


def _safe_numeric(value: Any) -> float | None:
    """Parse numeric-like values without raising on malformed payloads.

    Returns ``None`` for both legitimately-absent values (``None``, ``""``,
    ``"null"``) and non-finite/unparseable ones, so NaN/Inf never leak into the
    JSON response as bare ``NaN`` tokens.
    """
    if _is_null_like_numeric(value):
        return None
    if isinstance(value, str):
        value = value.strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_in_memory_trade_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one in-memory trade row to the /trade-feed response contract.

    Returns ``None`` for malformed rows so the endpoint doesn't surface partial
    debug payloads as real trades.
    """
    trade_id = (
        raw.get(FieldName.ID)
        or raw.get(FieldName.EXECUTION_TRACE_ID)
        or raw.get(FieldName.ORDER_ID)
    )
    symbol = raw.get(FieldName.SYMBOL)
    side = raw.get(FieldName.SIDE)
    if not trade_id or not symbol or not side:
        return None

    def _as_iso(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        if isinstance(value, str):
            return value
        return str(value)

    sanitized_fields: list[str] = []

    def _pick_num(name: str) -> float | None:
        raw_value = raw.get(name)
        parsed = _safe_numeric(raw_value)
        # Only a genuinely malformed value (e.g. "abc") counts as sanitized. A
        # null-like value (None / "" / "null" / "None") just means the field is
        # absent — normal for the exit price & P&L of a still-open position,
        # which must NOT be flagged as degraded.
        if parsed is None and not _is_null_like_numeric(raw_value):
            sanitized_fields.append(name)
        return parsed

    normalized = {
        FieldName.ID: str(trade_id),
        "symbol": str(symbol),
        "side": str(side),
        "qty": _pick_num(FieldName.QTY),
        "entry_price": _pick_num(FieldName.ENTRY_PRICE),
        "exit_price": _pick_num(FieldName.EXIT_PRICE),
        "pnl": _pick_num(FieldName.PNL),
        "pnl_percent": _pick_num(FieldName.PNL_PERCENT),
        "order_id": str(raw[FieldName.ORDER_ID]) if raw.get(FieldName.ORDER_ID) else None,
        FieldName.EXECUTION_TRACE_ID: raw.get(FieldName.EXECUTION_TRACE_ID),
        FieldName.SIGNAL_TRACE_ID: raw.get(FieldName.SIGNAL_TRACE_ID),
        "grade": raw.get(FieldName.GRADE),
        "grade_score": _pick_num(FieldName.GRADE_SCORE),
        FieldName.GRADE_LABEL: raw.get(FieldName.GRADE_LABEL),
        "status": raw.get(FieldName.STATUS) or "filled",
        "filled_at": _as_iso(raw.get(FieldName.FILLED_AT)),
        FieldName.GRADED_AT: _as_iso(raw.get(FieldName.GRADED_AT)),
        FieldName.REFLECTED_AT: _as_iso(raw.get(FieldName.REFLECTED_AT)),
        "created_at": _as_iso(raw.get(FieldName.CREATED_AT)),
        FieldName.SESSION_ID: raw.get(FieldName.SESSION_ID),
    }
    if sanitized_fields:
        normalized[FieldName.DEGRADED_REASON] = "invalid_numeric_fields_sanitized"
        normalized["sanitized_fields"] = sorted(set(sanitized_fields))
    return normalized


def _in_memory_trade_feed_payload(limit: int, session_id: str | None = None) -> dict[str, Any]:
    """Return normalized in-memory trade rows shaped to the trade-feed contract."""
    store = get_runtime_store()
    safe_limit = max(1, min(limit, 200))
    trades = [
        normalized
        for normalized in (
            _normalize_in_memory_trade_row(row) for row in reversed(store.trade_feed)
        )
        if normalized is not None
    ]
    if session_id:
        trades = [t for t in trades if str(t.get(FieldName.SESSION_ID) or "") == session_id]
    trades = trades[:safe_limit]
    return {
        FieldName.TRADES: trades,
        FieldName.COUNT: len(trades),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


def _fmt_db_trade_row(row: Any) -> dict[str, Any]:
    pnl = _safe_numeric(row[6])
    pnl_pct = _safe_numeric(row[7])
    return {
        FieldName.ID: str(row[0]),
        "symbol": row[1],
        "side": row[2],
        "qty": _safe_numeric(row[3]),
        "entry_price": _safe_numeric(row[4]),
        "exit_price": _safe_numeric(row[5]),
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pnl_percent": round(pnl_pct, 4) if pnl_pct is not None else None,
        "order_id": str(row[8]) if row[8] else None,
        FieldName.EXECUTION_TRACE_ID: row[9],
        FieldName.SIGNAL_TRACE_ID: row[10],
        "grade": row[11],
        "grade_score": _safe_numeric(row[12]),
        FieldName.GRADE_LABEL: row[13],
        "status": row[14],
        "filled_at": row[15].isoformat() if row[15] else None,
        FieldName.GRADED_AT: row[16].isoformat() if row[16] else None,
        FieldName.REFLECTED_AT: row[17].isoformat() if row[17] else None,
        "created_at": row[18].isoformat() if row[18] else None,
        FieldName.SESSION_ID: row[19],
    }


def _performance_trends_from_runtime_store(source: str = "in_memory") -> dict[str, Any]:
    """Build a performance-trends payload from the runtime store (no DB needed)."""
    store = get_runtime_store()
    paired = store.paired_pnl_payload()
    summary_data = paired[FieldName.SUMMARY]
    # Use the SAME order slice the paired summary was computed from — mixing
    # counts from one window with sums from another produced arithmetically
    # wrong averages once the store held more orders than the paired window.
    orders = paired[FieldName.CLOSED_TRADES]
    total_trades = summary_data[FieldName.CLOSED_TRADES]
    win_pnls = [
        float(o.get(FieldName.PNL) or 0.0) for o in orders if float(o.get(FieldName.PNL) or 0.0) > 0
    ]
    loss_pnls = [
        float(o.get(FieldName.PNL) or 0.0) for o in orders if float(o.get(FieldName.PNL) or 0.0) < 0
    ]
    avg_win = round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0.0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0
    return {
        "summary": {
            # Realized PnL only — matches the DB path (SUM(pnl) over closed
            # trades). Unrealized open-position PnL is exposed separately via the
            # paired-PnL / /pnl endpoints so "Total PnL" means the same thing in
            # both modes and never shows a phantom number next to zero closed fills.
            FieldName.TOTAL_PNL: summary_data[FieldName.REALIZED_PNL],
            FieldName.TOTAL_TRADES: total_trades,
            "win_rate": round(summary_data[FieldName.WIN_RATE_PERCENT] / 100.0, 4),
            FieldName.AVG_WIN: avg_win,
            FieldName.AVG_LOSS: avg_loss,
            FieldName.BEST_TRADE: round(
                max((float(o.get(FieldName.PNL) or 0.0) for o in orders), default=0.0), 2
            ),
            FieldName.WORST_TRADE: round(
                min((float(o.get(FieldName.PNL) or 0.0) for o in orders), default=0.0), 2
            ),
        },
        FieldName.DAILY_PNL: [],
        FieldName.GRADE_TREND: [],
        FieldName.EQUITY_CURVE: list(store.equity_curve[-200:]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        FieldName.HAS_DATA: bool(orders or store.open_positions()),
    }


async def get_trade_feed_payload(limit: int, session_id: str | None = None) -> dict[str, Any]:
    """Return the most recent trades with full lifecycle state."""
    if not is_db_available():
        payload = _in_memory_trade_feed_payload(limit, session_id=session_id)
        if payload[FieldName.COUNT] == 0:
            payload[FieldName.EMPTY_REASON] = "db_degraded"
        return payload
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        tl.id, tl.symbol, tl.side, tl.qty, tl.entry_price, tl.exit_price,
                        tl.pnl, tl.pnl_percent, tl.order_id,
                        tl.execution_trace_id, tl.signal_trace_id,
                        tl.grade, tl.grade_score, tl.grade_label,
                        tl.status, tl.filled_at, tl.graded_at, tl.reflected_at,
                        tl.created_at,
                        COALESCE(o.strategy_id::text, tl.decision_trace_id) AS session_id
                    FROM trade_lifecycle tl
                    LEFT JOIN orders o ON o.id::text = tl.order_id::text
                    ORDER BY COALESCE(filled_at, created_at) ASC
                    LIMIT :limit
                """),
                {FieldName.LIMIT: min(limit, 200)},
            )
            rows = result.all()

        trades = [_fmt_db_trade_row(r) for r in rows]
        if session_id:
            trades = [t for t in trades if str(t.get(FieldName.SESSION_ID) or "") == session_id]

        if not trades:
            async with AsyncSessionFactory() as session:
                fallback_result = await session.execute(
                    text("""
                        SELECT
                            o.id,
                            o.symbol,
                            o.side,
                            COALESCE(NULLIF(to_jsonb(o)->>'filled_quantity', '')::numeric, o.qty),
                            o.price,
                            o.status,
                            to_jsonb(o)->>'trace_id',
                            o.created_at,
                            o.filled_at,
                            o.strategy_id::text AS session_id
                        FROM orders o
                        WHERE status IN ('filled', 'executed')
                        ORDER BY COALESCE(filled_at, created_at) DESC
                        LIMIT :limit
                    """),
                    {FieldName.LIMIT: min(limit, 200)},
                )
                for row in fallback_result.all():
                    trades.append(
                        {
                            FieldName.ID: str(row[0]),
                            "symbol": row[1],
                            "side": row[2],
                            "qty": float(row[3]) if row[3] is not None else None,
                            "entry_price": float(row[4]) if row[4] is not None else None,
                            "exit_price": None,
                            "pnl": None,
                            "pnl_percent": None,
                            "order_id": str(row[0]),
                            FieldName.EXECUTION_TRACE_ID: row[6],
                            FieldName.SIGNAL_TRACE_ID: None,
                            "grade": None,
                            "grade_score": None,
                            FieldName.GRADE_LABEL: None,
                            "status": row[5],
                            "filled_at": row[8].isoformat() if row[8] else None,
                            FieldName.GRADED_AT: None,
                            FieldName.REFLECTED_AT: None,
                            "created_at": row[7].isoformat() if row[7] else None,
                            FieldName.SESSION_ID: row[9],
                        }
                    )
            if session_id:
                trades = [t for t in trades if str(t.get(FieldName.SESSION_ID) or "") == session_id]

        if not trades:
            fallback = _in_memory_trade_feed_payload(limit, session_id=session_id)
            if fallback[FieldName.COUNT] > 0:
                return fallback

            empty_reason = "no_executable_intents"
            try:
                _diag_params: dict[str, Any] = {}
                if session_id:
                    _order_sql = "SELECT COUNT(*) FROM orders WHERE strategy_id::text = :sid"
                    _lifecycle_sql = """
                        SELECT COUNT(*)
                        FROM trade_lifecycle tl
                        LEFT JOIN orders o ON o.id = tl.order_id
                        WHERE COALESCE(o.strategy_id::text, tl.decision_trace_id) = :sid
                    """
                    _diag_params = {FieldName.SID: session_id}
                else:
                    _order_sql = "SELECT COUNT(*) FROM orders"
                    _lifecycle_sql = "SELECT COUNT(*) FROM trade_lifecycle"
                async with AsyncSessionFactory() as diag_session:
                    order_count = (
                        await diag_session.execute(text(_order_sql), _diag_params)
                    ).scalar() or 0
                    lifecycle_count = (
                        await diag_session.execute(text(_lifecycle_sql), _diag_params)
                    ).scalar() or 0
                if order_count == 0:
                    empty_reason = "no_orders_executed"
                elif lifecycle_count == 0:
                    empty_reason = "lifecycle_not_persisted"
            except Exception:
                pass

            upstream: dict[str, Any] = {
                FieldName.SIGNAL_EVENTS: 0,
                FieldName.DECISIONS_EVALUATED: 0,
                FieldName.EE_LAST_STATUS: None,
            }
            try:
                _redis = await get_redis()
                upstream[FieldName.SIGNAL_EVENTS] = await _redis.xlen(STREAM_SIGNALS)
                upstream[FieldName.DECISIONS_EVALUATED] = await _redis.xlen(STREAM_DECISIONS)
                _ee_raw = await _redis.get(REDIS_AGENT_STATUS_KEY.format(name=AGENT_EXECUTION))
                if _ee_raw:
                    _ee = json.loads(_ee_raw)
                    upstream[FieldName.EE_LAST_STATUS] = _ee.get(FieldName.LAST_EVENT, "")
                    upstream[FieldName.EE_EVENT_COUNT] = int(_ee.get(FieldName.EVENT_COUNT, 0))
            except Exception:
                pass

            return {
                FieldName.TRADES: [],
                FieldName.COUNT: 0,
                FieldName.EMPTY_REASON: empty_reason,
                FieldName.UPSTREAM_ACTIVITY: upstream,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return {
            FieldName.TRADES: trades,
            FieldName.COUNT: len(trades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "trade_feed_failed", exc_info=True)
        return _in_memory_trade_feed_payload(limit, session_id=session_id)


async def get_performance_trends_payload() -> dict[str, Any]:
    """Return agent grade history and daily P&L for the last 30 days."""
    if not is_db_available():
        return _performance_trends_from_runtime_store()

    try:
        async with AsyncSessionFactory() as session:
            pnl_result = await session.execute(
                text("""
                    SELECT
                        DATE(filled_at AT TIME ZONE 'UTC') AS day,
                        SUM(pnl)                           AS daily_pnl,
                        COUNT(*)                           AS trade_count,
                        COUNT(*) FILTER (WHERE pnl > 0)    AS wins,
                        COUNT(*) FILTER (WHERE pnl <= 0)   AS losses,
                        AVG(pnl)                           AS avg_pnl
                    FROM trade_lifecycle
                    WHERE filled_at >= NOW() - INTERVAL '30 days'
                      AND status IN ('filled', 'graded', 'reflected')
                    GROUP BY day
                    ORDER BY day DESC
                """)
            )
            daily_pnl = [
                {
                    FieldName.DAY: str(r[0]),
                    "pnl": round(float(r[1]), 2) if r[1] is not None else 0.0,
                    FieldName.TRADE_COUNT: int(r[2]),
                    FieldName.WINS: int(r[3]),
                    FieldName.LOSSES: int(r[4]),
                    FieldName.AVG_PNL: round(float(r[5]), 2) if r[5] is not None else 0.0,
                }
                for r in pnl_result.all()
            ]

            grade_result = await session.execute(
                text("""
                    SELECT
                        DATE(created_at AT TIME ZONE 'UTC') AS day,
                        AVG(score)                           AS avg_score_pct
                    FROM agent_grades
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY day
                    ORDER BY day DESC
                """)
            )
            grade_trend = [
                {
                    FieldName.DAY: str(r[0]),
                    FieldName.AVG_SCORE_PCT: round(float(r[1]), 1) if r[1] is not None else None,
                }
                for r in grade_result.all()
            ]

            summary_result = await session.execute(
                text("""
                    SELECT
                        COALESCE(SUM(pnl), 0)                       AS total_pnl,
                        COUNT(*)                                     AS total_trades,
                        COUNT(*) FILTER (WHERE pnl > 0)             AS total_wins,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0) AS avg_win,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl < 0), 0) AS avg_loss,
                        COALESCE(MAX(pnl), 0)                        AS best_trade,
                        COALESCE(MIN(pnl), 0)                        AS worst_trade
                    FROM trade_lifecycle
                    WHERE status IN ('filled', 'graded', 'reflected')
                """)
            )
            s = summary_result.first()
            total_trades = int(s[1]) if s else 0
            total_wins = int(s[2]) if s else 0
            summary = {
                FieldName.TOTAL_PNL: round(float(s[0]), 2) if s else 0.0,
                FieldName.TOTAL_TRADES: total_trades,
                "win_rate": round(total_wins / total_trades, 4) if total_trades else 0.0,
                FieldName.AVG_WIN: round(float(s[3]), 2) if s else 0.0,
                FieldName.AVG_LOSS: round(float(s[4]), 2) if s else 0.0,
                FieldName.BEST_TRADE: round(float(s[5]), 2) if s else 0.0,
                FieldName.WORST_TRADE: round(float(s[6]), 2) if s else 0.0,
            }

        return {
            "summary": summary,
            FieldName.DAILY_PNL: daily_pnl,
            FieldName.GRADE_TREND: grade_trend,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "performance_trends_failed", exc_info=True)
        return _performance_trends_from_runtime_store(source="db_error")
