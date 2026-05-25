from __future__ import annotations

import time
from typing import Annotated

from api.services.learning_service import LearningService
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from api.constants import FieldName, PositionSide
from api.core.models import AgentRun, TradePerformance
from api.database import get_async_session
from api.main_state import get_learning_service

router = APIRouter(tags=["performance"])
_STATS_CACHE: dict[str, object] = {FieldName.EXPIRES_AT: 0.0, FieldName.PAYLOAD: None}


@router.get("/api/performance/{agent_name}")
async def get_agent_performance(
    agent_name: str,
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
):
    async with get_async_session() as session:
        return await learning_service.get_agent_performance(agent_name, session)


@router.get("/api/performance")
async def get_all_performance(
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
):
    async with get_async_session() as session:
        output = {}
        for agent_name in learning_service.agent_performance.keys():
            try:
                output[agent_name] = await learning_service.get_agent_performance(
                    agent_name, session
                )
            except HTTPException:
                continue
        return output


@router.get("/api/statistics")
async def get_statistics(force_refresh: bool = False):
    now = time.time()
    if (
        not force_refresh
        and _STATS_CACHE[FieldName.PAYLOAD]
        and now < float(_STATS_CACHE[FieldName.EXPIRES_AT])
    ):
        return _STATS_CACHE[FieldName.PAYLOAD]

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
            "win_rate": round((wins / total_trades * 100), 2) if total_trades else 0,
            FieldName.TOTAL_PNL: round(total_pnl, 2),
            FieldName.CACHED_UNTIL_EPOCH: int(now + 15),
        }
        _STATS_CACHE[FieldName.PAYLOAD] = payload
        _STATS_CACHE[FieldName.EXPIRES_AT] = now + 15
        return payload


@router.get("/api/runs")
async def get_recent_runs(limit: int = 20):
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
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }
