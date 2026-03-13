from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from api.core.models import AgentRun, ClosedPlayEvalRequest, LearningSummaryRequest, OptionsGenerateRequest
from api.database import get_async_session
from api.main_state import get_memory_service, get_options_service

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/health")
async def options_health(options_service=Depends(get_options_service)):
    return options_service.get_health()


@router.get("/flow")
async def get_options_flow(options_service=Depends(get_options_service)):
    return {"items": options_service.get_flow()}


@router.get("/screener")
async def get_options_screener(options_service=Depends(get_options_service)):
    return {"items": options_service.get_screener()}


@router.get("/ticker/{symbol}")
async def get_ticker_snapshot(symbol: str, options_service=Depends(get_options_service)):
    return {"item": options_service.get_ticker_details(symbol)}


@router.post("/plays/generate")
async def generate_options_plays(
    request: OptionsGenerateRequest,
    options_service=Depends(get_options_service),
    memory_service=Depends(get_memory_service),
):
    output = options_service.generate_plays(request.flow, request.screener, request.learning_context)
    run_entry = options_service.build_run_record(output)

    async with get_async_session() as session:
        await memory_service.persist_run(session, run_entry)

    return output


@router.post("/plays/close")
async def close_options_play(request: ClosedPlayEvalRequest, options_service=Depends(get_options_service)):
    evaluation = options_service.evaluate_closed_play(request.play, request.pnl, request.recent_flow)
    return {"evaluation": evaluation}


@router.post("/learning/summary")
async def options_learning_summary(request: LearningSummaryRequest, options_service=Depends(get_options_service)):
    return options_service.learning_summary(request.history)


@router.get("/performance")
async def options_performance(options_service=Depends(get_options_service)):
    return options_service.get_performance()


@router.get("/performance/{agent_name}")
async def options_agent_performance(agent_name: str, options_service=Depends(get_options_service)):
    return options_service.get_performance().get(agent_name.upper(), {})


@router.get("/statistics")
async def options_statistics(options_service=Depends(get_options_service)):
    return options_service.get_statistics()


@router.get("/runs")
async def options_runs(limit: int = 20):
    async with get_async_session() as session:
        rows = (
            await session.execute(
                select(AgentRun).where(AgentRun.task_id.like("options-%")).order_by(AgentRun.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        return {
            "runs": [
                {
                    "id": row.id,
                    "task_id": row.task_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
        }
