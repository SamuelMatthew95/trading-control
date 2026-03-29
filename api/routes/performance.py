from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text

from api.core.models import AgentRun, TradePerformance
from api.database import get_async_session

router = APIRouter(prefix="/performance", tags=["performance"])
_STATS_CACHE: dict[str, object] = {"expires_at": 0.0, "payload": None}


@router.get("/{agent_name}")
async def get_agent_performance(agent_name: str):
    async with get_async_session() as session:
        # Simple query for agent performance data
        result = await session.execute(
            text("SELECT * FROM agent_performance WHERE agent_name = :agent_name ORDER BY created_at DESC LIMIT 100"),
            {"agent_name": agent_name}
        )
        return [dict(row._mapping) for row in result]


@router.get("/")
async def get_all_performance():
    async with get_async_session() as session:
        # Simple query for all agent performance
        result = await session.execute(
            text("SELECT DISTINCT agent_name FROM agent_performance ORDER BY agent_name")
        )
        agent_names = [row.agent_name for row in result]
        
        output = {}
        for agent_name in agent_names:
            try:
                agent_result = await session.execute(
                    text("SELECT * FROM agent_performance WHERE agent_name = :agent_name ORDER BY created_at DESC LIMIT 10"),
                    {"agent_name": agent_name}
                )
                output[agent_name] = [dict(row._mapping) for row in agent_result]
            except Exception:
                continue
        return output


@router.get("/api/statistics")
async def get_statistics(force_refresh: bool = False):
    now = time.time()
    if (
        not force_refresh
        and _STATS_CACHE["payload"]
        and now < float(_STATS_CACHE["expires_at"])
    ):
        return _STATS_CACHE["payload"]

    async with get_async_session() as session:
        total_trades = (
            await session.execute(select(func.count(TradePerformance.id)))
        ).scalar() or 0
        wins = (
            await session.execute(
                select(func.count(TradePerformance.id)).where(TradePerformance.trade_type == "long")
            )
        ).scalar() or 0
        losses = (
            await session.execute(
                select(func.count(TradePerformance.id)).where(TradePerformance.trade_type == "short")
            )
        ).scalar() or 0
        total_pnl = (
            await session.execute(
                select(func.sum(TradePerformance.pnl)).where(TradePerformance.pnl.is_not(None))
            )
        ).scalar() or 0
        payload = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total_trades * 100), 2) if total_trades else 0,
            "total_pnl": round(total_pnl, 2),
            "cached_until_epoch": int(now + 15),
        }
        _STATS_CACHE["payload"] = payload
        _STATS_CACHE["expires_at"] = now + 15
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
            "runs": [
                {
                    "id": r.id,
                    "task_id": r.task_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }
