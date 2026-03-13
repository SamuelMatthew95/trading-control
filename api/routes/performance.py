from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from api.core.models import AgentRun, Trade
from api.main_state import get_learning_service
from api.database import get_async_session

router = APIRouter(tags=["performance"])


@router.get("/api/performance/{agent_name}")
async def get_agent_performance(agent_name: str, learning_service=Depends(get_learning_service)):
    async with get_async_session() as session:
        return await learning_service.get_agent_performance(agent_name, session)


@router.get("/api/performance")
async def get_all_performance(learning_service=Depends(get_learning_service)):
    async with get_async_session() as session:
        output = {}
        for agent_name in learning_service.agent_performance.keys():
            try:
                output[agent_name] = await learning_service.get_agent_performance(agent_name, session)
            except HTTPException:
                continue
        return output


@router.get("/api/statistics")
async def get_statistics():
    async with get_async_session() as session:
        total_trades = (await session.execute(select(func.count(Trade.id)))).scalar() or 0
        wins = (await session.execute(select(func.count(Trade.id)).where(Trade.outcome == "WIN"))).scalar() or 0
        losses = (await session.execute(select(func.count(Trade.id)).where(Trade.outcome == "LOSS"))).scalar() or 0
        total_pnl = (await session.execute(select(func.sum(Trade.pnl)).where(Trade.pnl.is_not(None)))).scalar() or 0
        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total_trades * 100), 2) if total_trades else 0,
            "total_pnl": round(total_pnl, 2),
        }


@router.get("/api/runs")
async def get_recent_runs(limit: int = 20):
    async with get_async_session() as session:
        rows = (await session.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit))).scalars().all()
        return {"runs": [{"id": r.id, "task_id": r.task_id, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}
