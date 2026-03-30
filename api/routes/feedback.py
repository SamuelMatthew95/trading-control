from __future__ import annotations

from typing import Annotated, Any

from api.services.feedback_service import FeedbackService
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.core.models import AnnotationCreate, ReinforceRequest
from api.database import get_async_session
from api.main_state import get_feedback_service

router = APIRouter(tags=["feedback"])


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None


@router.post("/memory/annotations")
async def create_annotation(
    payload: AnnotationCreate,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async with get_async_session() as session:
        row = await feedback_service.stage_annotation(session, payload.model_dump())
        return {"id": row.id, "status": row.feedback_status}


@router.post("/memory/negative")
async def create_negative_memory(
    payload: dict,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async with get_async_session() as session:
        row = await feedback_service.create_negative_memory(session, payload)
        return {"id": row.id, "status": "stored"}


@router.post("/feedback/reinforce")
async def reinforce_feedback(
    payload: ReinforceRequest,
    background_tasks: BackgroundTasks,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async with get_async_session() as session:
        job = await feedback_service.create_feedback_job(session, payload.run_id)
        job_id = job.id

    async def _run_pipeline() -> None:
        async with get_async_session() as session:
            await feedback_service.run_feedback_job(session, job_id, payload)

    background_tasks.add_task(_run_pipeline)
    return {"status": "queued", "run_id": payload.run_id, "job_id": job_id}


@router.get("/feedback/reinforce/{job_id}")
async def get_reinforce_job(
    job_id: str,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async with get_async_session() as session:
        row = await feedback_service.get_feedback_job(session, job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="feedback job not found")
        return row.model_dump()


@router.post("/insights/rebuild")
async def rebuild_insights(
    background_tasks: BackgroundTasks,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async def _run() -> None:
        async with get_async_session() as session:
            await feedback_service.run_supervisor_pass(session, lookback_runs=50)

    background_tasks.add_task(_run)
    return {"status": "queued"}


@router.get("/insights")
async def get_insights(
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
    limit: int = 50,
):
    try:
        async with get_async_session() as session:
            insights = await feedback_service.list_insights(session, limit=limit)
            insights_data = {"items": [entry.model_dump() for entry in insights]}
            return StandardResponse(success=True, data=insights_data).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get insights: {str(e)}") from None


@router.get("/runs/propose")
async def propose_runs(
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async with get_async_session() as session:
        items = await feedback_service.propose_runs(session)
        return {"stage": "Proposed", "items": [item.model_dump() for item in items]}


@router.post("/memory/positive")
async def create_positive_memory(
    payload: dict,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
):
    async with get_async_session() as session:
        payload = {**payload, "store_type": "few-shot"}
        row = await feedback_service.create_negative_memory(session, payload)
        row.store_type = "few-shot"
        return {"id": row.id, "status": "stored"}


@router.post("/config/blocklist")
async def config_blocklist(payload: dict):
    return {"status": "accepted", "blocked_tools": payload.get("tools", [])}
