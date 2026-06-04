"""Performance / statistics endpoints.

Per-agent performance comes from the in-memory
:class:`~api.services.learning_service.LearningService` rollup. Aggregate
statistics and recent runs query Postgres when available and fall back to the
in-memory runtime store (memory mode) so the endpoints always return real data
without ever 500-ing.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.constants import FieldName, PositionSide
from api.core.models import AgentRun, TradePerformance
from api.database import get_async_session
from api.main_state import get_learning_service
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.learning_service import LearningService
from api.services.metrics_calc import closed_trade_stats

router = APIRouter(tags=["performance"])
_STATS_CACHE: dict[str, object] = {FieldName.EXPIRES_AT: 0.0, FieldName.PAYLOAD: None}


@router.get("/api/performance/{agent_name}")
async def get_agent_performance(
    agent_name: str,
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
) -> dict[str, Any]:
    return await learning_service.get_agent_performance(agent_name)


@router.get("/api/performance")
async def get_all_performance(
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for agent_name in learning_service.agent_performance:
        output[agent_name] = await learning_service.get_agent_performance(agent_name)
    return output


def _memory_statistics(now: float) -> dict[str, Any]:
    """Aggregate stats from the in-memory runtime store (DB-down path)."""
    store = get_runtime_store()
    stats = closed_trade_stats(list(store.orders))
    total = stats.winning + stats.losing
    return {
        FieldName.TOTAL_TRADES: total,
        FieldName.WINS: stats.winning,
        FieldName.LOSSES: stats.losing,
        FieldName.WIN_RATE: round(stats.win_rate * 100, 2),
        FieldName.TOTAL_PNL: round(stats.realized_pnl, 2),
        FieldName.CACHED_UNTIL_EPOCH: int(now + 15),
        FieldName.SOURCE: "in_memory",
    }


@router.get("/api/statistics")
async def get_statistics(force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if (
        not force_refresh
        and _STATS_CACHE[FieldName.PAYLOAD]
        and now < float(_STATS_CACHE[FieldName.EXPIRES_AT])
    ):
        return _STATS_CACHE[FieldName.PAYLOAD]  # type: ignore[return-value]

    if not is_db_available():
        payload = _memory_statistics(now)
        _STATS_CACHE[FieldName.PAYLOAD] = payload
        _STATS_CACHE[FieldName.EXPIRES_AT] = now + 15
        return payload

    try:
        async with get_async_session() as session:
            total_trades = (
                await session.execute(select(func.count(TradePerformance.id)))
            ).scalar() or 0
            wins = (
                await session.execute(
                    select(func.count(TradePerformance.id)).where(
                        TradePerformance.trade_type == PositionSide.LONG
                    )
                )
            ).scalar() or 0
            losses = (
                await session.execute(
                    select(func.count(TradePerformance.id)).where(
                        TradePerformance.trade_type == PositionSide.SHORT
                    )
                )
            ).scalar() or 0
            total_pnl = (
                await session.execute(
                    select(func.sum(TradePerformance.pnl)).where(TradePerformance.pnl.is_not(None))
                )
            ).scalar() or 0
            payload = {
                FieldName.TOTAL_TRADES: total_trades,
                FieldName.WINS: wins,
                FieldName.LOSSES: losses,
                FieldName.WIN_RATE: round((wins / total_trades * 100), 2) if total_trades else 0,
                FieldName.TOTAL_PNL: round(total_pnl, 2),
                FieldName.CACHED_UNTIL_EPOCH: int(now + 15),
                FieldName.SOURCE: "database",
            }
    except Exception:
        log_structured("warning", "statistics_db_unavailable", exc_info=True)
        payload = _memory_statistics(now)

    _STATS_CACHE[FieldName.PAYLOAD] = payload
    _STATS_CACHE[FieldName.EXPIRES_AT] = now + 15
    return payload


@router.get("/api/runs")
async def get_recent_runs(limit: int = 20) -> dict[str, Any]:
    if not is_db_available():
        store = get_runtime_store()
        # Newest-first, projected to the same {id, task_id, created_at} contract
        # the DB branch returns so the endpoint shape is mode-independent.
        rows = list(getattr(store, "agent_runs", []))[-limit:][::-1]
        runs = [
            {
                FieldName.ID: r.get(FieldName.ID),
                FieldName.TASK_ID: r.get(FieldName.TASK_ID),
                FieldName.CREATED_AT: r.get(FieldName.CREATED_AT),
            }
            for r in rows
        ]
        return {FieldName.RUNS: runs, FieldName.SOURCE: "in_memory"}

    try:
        async with get_async_session() as session:
            rows = (
                (
                    await session.execute(
                        select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return {
                FieldName.RUNS: [
                    {
                        FieldName.ID: r.id,
                        FieldName.TASK_ID: r.task_id,
                        FieldName.CREATED_AT: r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
                FieldName.SOURCE: "database",
            }
    except Exception:
        log_structured("warning", "recent_runs_db_unavailable", exc_info=True)
        return {FieldName.RUNS: [], FieldName.SOURCE: "in_memory"}
