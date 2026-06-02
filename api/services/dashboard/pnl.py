from datetime import datetime, timezone
from typing import Any

from api.constants import FieldName
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.metrics_aggregator import MetricsAggregator
from api.services.metrics_calc import closed_trade_stats


def _in_memory_pnl_payload() -> dict[str, Any]:
    """Compute dashboard PnL metrics directly from in-memory runtime state.

    Realized PnL, win/loss counts, win rate, and best/worst all derive from the
    canonical ``closed_trade_stats`` so this endpoint agrees with the paired-PnL
    view and the metrics aggregator. Opening fills (pnl=None) never count toward
    the win-rate denominator.
    """
    store = get_runtime_store()
    orders = list(store.orders)
    open_positions = store.open_positions()
    stats = closed_trade_stats(orders)
    equity_curve = list(store.equity_curve[-200:])

    return {
        "pnl": orders[-100:],
        FieldName.TOTAL_PNL: round(stats.realized_pnl, 2),
        FieldName.WINNING_TRADES: stats.winning,
        FieldName.LOSING_TRADES: stats.losing,
        "win_rate": round(stats.win_rate, 4),
        FieldName.ACTIVE_POSITIONS: len(open_positions),
        FieldName.BEST_TRADE: round(stats.best, 2),
        FieldName.WORST_TRADE: round(stats.worst, 2),
        FieldName.EQUITY_CURVE: equity_curve,
        FieldName.HAS_DATA: bool(orders or open_positions or equity_curve),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


def _paired_pnl_memory_payload() -> dict[str, Any]:
    payload = get_runtime_store().paired_pnl_payload()
    return {
        FieldName.CLOSED_TRADES: payload[FieldName.CLOSED_TRADES],
        FieldName.OPEN_POSITIONS: payload[FieldName.OPEN_POSITIONS],
        "summary": payload[FieldName.SUMMARY],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


async def get_pnl_payload() -> dict[str, Any]:
    """Get PnL metrics."""
    if not is_db_available():
        return _in_memory_pnl_payload()
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_pnl_metrics()

    except Exception:
        log_structured("warning", "pnl_metrics_db_unavailable", exc_info=True)
        return _in_memory_pnl_payload()


async def get_paired_pnl_payload(redis_client: Any) -> dict[str, Any]:
    """Paired P&L view: closed BUY->SELL pairs with realized PnL + open positions
    with live unrealized PnL enriched from the Redis price cache.

    Closed trades come from ``trade_lifecycle`` (one row per completed round-trip).
    Open positions are read from the ``positions`` table and enriched with current
    price so unrealized PnL updates on every request.
    """
    if not is_db_available():
        return _paired_pnl_memory_payload()

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_paired_pnl(redis_client=redis_client)
    except Exception:
        log_structured("warning", "paired_pnl_unavailable", exc_info=True)
        return _paired_pnl_memory_payload()
