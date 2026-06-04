"""Feedback / reinforcement endpoints.

Backed by the in-memory :class:`~api.services.feedback_service.FeedbackService`
(resolved through ``api.main_state``). The durable reinforcement pipeline is not
yet implemented; these endpoints provide a stable, never-erroring contract so
the dashboard's feedback surface works in every runtime mode.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.constants import FieldName
from api.core.schemas import AnnotationCreate, ReinforceRequest, StandardResponse
from api.main_state import get_feedback_service
from api.services.feedback_service import FeedbackService

router = APIRouter(tags=["feedback"])


@router.post("/memory/annotations")
async def create_annotation(
    payload: AnnotationCreate,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    row = await feedback_service.stage_annotation(payload.model_dump())
    return {FieldName.ID: row.id, FieldName.STATUS: row.feedback_status}


@router.post("/memory/negative")
async def create_negative_memory(
    payload: dict,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    row = await feedback_service.create_negative_memory(payload)
    return {FieldName.ID: row.id, FieldName.STATUS: "stored"}


@router.post("/memory/positive")
async def create_positive_memory(
    payload: dict,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    row = await feedback_service.create_positive_memory(payload)
    return {FieldName.ID: row.id, FieldName.STATUS: "stored"}


@router.post("/feedback/reinforce")
async def reinforce_feedback(
    payload: ReinforceRequest,
    background_tasks: BackgroundTasks,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    job = await feedback_service.create_feedback_job(payload.run_id)
    job_id = job.id
    background_tasks.add_task(feedback_service.run_feedback_job, job_id, payload)
    return {FieldName.STATUS: "queued", FieldName.RUN_ID: payload.run_id, FieldName.JOB_ID: job_id}


@router.get("/feedback/reinforce/{job_id}")
async def get_reinforce_job(
    job_id: str,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    row = await feedback_service.get_feedback_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="feedback job not found")
    return row.model_dump()


@router.post("/insights/rebuild")
async def rebuild_insights(
    background_tasks: BackgroundTasks,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    background_tasks.add_task(feedback_service.run_supervisor_pass, 50)
    return {FieldName.STATUS: "queued"}


@router.get("/insights")
async def get_insights(
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
    limit: int = 50,
) -> dict[str, Any]:
    insights = await feedback_service.list_insights(limit=limit)
    data = {FieldName.ITEMS: [entry.model_dump() for entry in insights]}
    return StandardResponse(success=True, data=data).model_dump()


@router.get("/runs/propose")
async def propose_runs(
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> dict[str, Any]:
    items = await feedback_service.propose_runs()
    return {FieldName.STAGE: "Proposed", FieldName.ITEMS: [item.model_dump() for item in items]}


@router.post("/config/blocklist")
async def config_blocklist(payload: dict) -> dict[str, Any]:
    return {FieldName.STATUS: "accepted", FieldName.BLOCKED_TOOLS: payload.get(FieldName.TOOLS, [])}
