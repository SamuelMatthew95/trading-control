from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select

from api.core.models import (
    FeedbackJob,
    HealthSignalView,
    Insight,
    LearningVelocityResponse,
    PnlResponse,
    Run,
    RunSummaryRowView,
    Signal,
    StrategyDNA,
    SystemHealth,
    TaskTypeBaseline,
    TraceStep,
    VectorMemoryRecord,
)
from api.database import get_async_session
from api.services.learning import AgentLearningService

router = APIRouter(tags=["dashboard"])
LAST_SIGNAL_GENERATION: Optional[datetime] = None
LAST_SIGNAL_GENERATION_STATUS: str = "never"
SCHEDULER_RUNNING: bool = False


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None


def _utc_midnight(reference_dt: datetime, day_shift: int = 0) -> datetime:
    now = reference_dt.astimezone(timezone.utc)
    base = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return (base + timedelta(days=day_shift)).replace(tzinfo=None)


def _trend(series: List[float | None]) -> str:
    vals = [v for v in series if v is not None]
    if len(vals) < 5:
        return "plateauing"
    y = vals[-5:]
    x = [0, 1, 2, 3, 4]
    x_mean = sum(x) / 5
    y_mean = sum(y) / 5
    slope = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y)) / (sum((xi - x_mean) ** 2 for xi in x) or 1)
    if slope > 0.01:
        return "improving"
    if slope < -0.05:
        return "regressing"
    return "plateauing"


@router.get("/dashboard/pnl")
async def dashboard_pnl(response: Response, reference_dt: Optional[datetime] = None):
    try:
        now = reference_dt or datetime.utcnow()
        today = _utc_midnight(now, 0)
        yesterday = _utc_midnight(now, -1)
        thirty_days = now - timedelta(days=30)

        async with get_async_session() as session:
            row = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(Run.pnl), 0.0).label("total_pnl"),
                        func.coalesce(func.sum(case((Run.created_at >= today, Run.pnl), else_=0.0)), 0.0).label("pnl_today"),
                        func.coalesce(func.sum(case((and_(Run.created_at >= yesterday, Run.created_at < today), Run.pnl), else_=0.0)), 0.0).label("pnl_yesterday"),
                        func.coalesce(func.avg(case((and_(Run.created_at >= thirty_days, TaskTypeBaseline.baseline_slippage.is_not(None), Run.actual_slippage.is_not(None)), TaskTypeBaseline.baseline_slippage - Run.actual_slippage), else_=None)), 0.0).label("avg_slippage_saved"),
                    ).select_from(Run).join(TaskTypeBaseline, TaskTypeBaseline.task_type == Run.task_type, isouter=True)
                )
            ).one()
            execution_cost = float((await session.execute(select(func.coalesce(func.sum(TraceStep.token_cost_usd), 0.0)))).scalar() or 0.0)

        pnl_today = float(row.pnl_today or 0.0)
        pnl_yesterday = float(row.pnl_yesterday or 0.0)
        pct = 0.0 if pnl_yesterday == 0 else ((pnl_today - pnl_yesterday) / abs(pnl_yesterday)) * 100
        total_pnl = float(row.total_pnl or 0.0)
        response.headers["Cache-Control"] = "no-store"
        
        pnl_data = PnlResponse(
            total_pnl=round(total_pnl, 2),
            pnl_today=round(pnl_today, 2),
            pnl_today_pct_change=round(pct, 2),
            avg_slippage_saved=round(float(row.avg_slippage_saved or 0.0), 4),
            execution_cost=round(execution_cost, 2),
            net_alpha=round(total_pnl - execution_cost, 2),
        )
        
        return StandardResponse(success=True, data=pnl_data.model_dump()).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get PNL data: {str(e)}")


@router.get("/dashboard/learning-velocity")
async def dashboard_learning_velocity(response: Response, reference_dt: Optional[datetime] = None):
    try:
        now = reference_dt or datetime.utcnow()
        since = _utc_midnight(now, -29)
        async with get_async_session() as session:
            pass_rows = (await session.execute(select(func.date(Run.created_at), func.count(Run.id), func.sum(case((Run.status == "won", 1), else_=0))).where(Run.created_at >= since).group_by(func.date(Run.created_at)))).all()
            coh_rows = (await session.execute(select(func.date(Run.created_at), func.avg(Run.reasoning_coherence_score)).where(Run.created_at >= since).group_by(func.date(Run.created_at)))).all()
            pass_map = {str(d): (w / t * 100 if t else None) for d, t, w in pass_rows}
            coh_map = {str(d): (float(c) * 10 if c is not None else None) for d, c in coh_rows}

            passk_series: list[float | None] = []
            coherence_series: list[float | None] = []
            for i in range(30):
                day = (_utc_midnight(now, -29 + i)).date().isoformat()
                passk_series.append(pass_map.get(day))
                coherence_series.append(coh_map.get(day))

            annotations_this_week = int((await session.execute(select(func.count(VectorMemoryRecord.id)).where(VectorMemoryRecord.created_at >= now - timedelta(days=7)))).scalar() or 0)
            good, total = (
                await session.execute(
                    select(func.sum(case((Run.pnl > 0, 1), else_=0)), func.count(TraceStep.id))
                    .join(Run, Run.id == TraceStep.run_id)
                    .where(TraceStep.step_type == "skipped_by_memory_guard", TraceStep.created_at >= now - timedelta(days=7))
                )
            ).one()
            verified = (await session.execute(select(func.avg(func.julianday(VectorMemoryRecord.correction_verified_at) - func.julianday(VectorMemoryRecord.created_at))).where(VectorMemoryRecord.correction_verified_at.is_not(None)))).scalar()
            pending_or_failed = int((await session.execute(select(func.count(Run.id)).where(Run.created_at >= since, Run.scoring_status.in_(["pending", "failed"])))).scalar() or 0)
            total_recent = int((await session.execute(select(func.count(Run.id)).where(Run.created_at >= since))).scalar() or 0)

        guard_pct = 0.0 if not total else float(good or 0) / float(total) * 100
        response.headers["Cache-Control"] = "max-age=120"
        
        learning_data = LearningVelocityResponse(
            passk_series=passk_series,
            coherence_series=coherence_series,
            passk_trend=_trend(passk_series),
            annotations_this_week=annotations_this_week,
            avg_sessions_to_correction=None if verified is None else round(float(verified), 2),
            memory_guard_effectiveness_pct=round(guard_pct, 2),
            scoring_lag_warning=(total_recent >= 10 and pending_or_failed > 5 and pending_or_failed / total_recent > 0.2),
        )
        
        return StandardResponse(success=True, data=learning_data.model_dump()).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get learning velocity data: {str(e)}")


@router.get("/dashboard/health-signals")
async def dashboard_health_signals(response: Response, reference_dt: Optional[datetime] = None):
    try:
        now = reference_dt or datetime.utcnow()
        async with get_async_session() as session:
            context_ratio = float((await session.execute(select(func.coalesce(func.avg((TraceStep.tokens_used * 1.0) / func.nullif(TraceStep.context_limit, 0)), 0.0)).where(TraceStep.context_limit.is_not(None), TraceStep.tokens_used.is_not(None)))).scalar() or 0.0)
            recent_runs = (await session.execute(select(Run.id).where(Run.created_at >= now - timedelta(days=7)))).scalars().all()
            thrash_runs = 0
            for rid in recent_runs:
                tools = (await session.execute(select(TraceStep.tool_name).where(TraceStep.run_id == rid).order_by(TraceStep.id.asc()))).scalars().all()
                streak = 1
                for i in range(1, len(tools)):
                    if tools[i] and tools[i] == tools[i - 1]:
                        streak += 1
                        if streak >= 3:
                            thrash_runs += 1
                            break
                    else:
                        streak = 1
            thrash_rate = 0.0 if not recent_runs else thrash_runs / len(recent_runs) * 100
            errors = int((await session.execute(select(func.count(func.distinct(TraceStep.run_id))).where(TraceStep.step_type == "error"))).scalar() or 0)
            recovered = int((await session.execute(select(func.count(func.distinct(TraceStep.run_id))).where(TraceStep.step_type == "recovery"))).scalar() or 0)
            recovery_rate = 0.0 if errors == 0 else recovered / errors * 100
            constraint = int((await session.execute(select(func.count(TraceStep.id)).where(TraceStep.step_type == "constraint_violation", TraceStep.created_at >= now - timedelta(days=7)))).scalar() or 0)
            ghost_delta = float((await session.execute(select(func.coalesce(func.avg(Run.actual_slippage - Run.ghost_slippage), 0.0)).where(Run.ghost_run_id.is_not(None)))).scalar() or 0.0)
            guard_hits = int((await session.execute(select(func.count(TraceStep.id)).where(TraceStep.step_type == "skipped_by_memory_guard", TraceStep.created_at >= now - timedelta(days=7)))).scalar() or 0)
        response.headers["Cache-Control"] = "max-age=60"
        
        health_signals = {
            "items": [
                HealthSignalView(key="context_saturation", label="Context saturation", value=f"{context_ratio*100:.1f}%", status="red" if context_ratio > 0.75 else "green", interpretation="High means prompts are near token ceiling.").model_dump(),
                HealthSignalView(key="tool_thrashing_rate", label="Tool thrashing rate", value=f"{thrash_rate:.1f}%", status="red" if thrash_rate > 20 else "amber", interpretation="Repeated tool loops indicate unstable planning.").model_dump(),
                HealthSignalView(key="recovery_rate", label="Recovery rate", value=f"{recovery_rate:.1f}%", status="green" if recovery_rate > 65 else "amber", interpretation="How often failures self-correct before final decision.").model_dump(),
                HealthSignalView(key="constraint_violations", label="Constraint violations", value=str(constraint), status="red" if constraint > 0 else "green", interpretation="Any violation should be reviewed immediately.").model_dump(),
                HealthSignalView(key="ghost_path_delta", label="Ghost path delta", value=f"{ghost_delta:.3f}", status="green" if ghost_delta > 0 else "amber", interpretation="Positive means current path beats ghost baseline.").model_dump(),
                HealthSignalView(key="memory_guard_hits", label="Memory guard hits", value=str(guard_hits), status="blue", interpretation="Informational count of blocked risky tool calls.").model_dump(),
            ]
        }
        
        return StandardResponse(success=True, data=health_signals).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get health signals: {str(e)}")


@router.get("/dashboard/run-summary")
async def dashboard_run_summary(response: Response, reference_dt: Optional[datetime] = None):
    try:
        now = reference_dt or datetime.utcnow()
        since = now - timedelta(days=7)
        async with get_async_session() as session:
            groups = (
                await session.execute(
                    select(
                        Run.task_type,
                        func.count(Run.id),
                        (func.sum(case((Run.status == "won", 1), else_=0)) * 100.0 / func.nullif(func.sum(case((Run.status.in_(["won", "failed"]), 1), else_=0)), 0)),
                        func.avg(Run.step_count),
                        func.avg(Run.pnl),
                    )
                    .where(Run.created_at >= since)
                    .group_by(Run.task_type)
                    .order_by(func.count(Run.id).desc())
                    .limit(20)
                )
            ).all()

            items: list[RunSummaryRowView] = []
            for task_type, runs_7d, win_rate, avg_steps, avg_pnl in groups:
                baseline = float((await session.execute(select(func.coalesce(func.avg(Run.step_count), 0.0)).where(Run.task_type == task_type, Run.created_at < now - timedelta(days=30)))).scalar() or 0.0)
                daily = (await session.execute(select(func.date(Run.created_at), func.coalesce(func.avg(Run.pnl), 0.0)).where(Run.task_type == task_type, Run.created_at >= since).group_by(func.date(Run.created_at)))).all()
                dmap = {str(d): float(v) for d, v in daily}
                sparkline = [round(dmap.get((now - timedelta(days=6 - i)).date().isoformat(), 0.0), 2) for i in range(7)]
                items.append(RunSummaryRowView(task_type=task_type, task_slug=task_type.lower().replace(" ", "_"), runs_7d=int(runs_7d), win_rate_pct=round(float(win_rate or 0.0), 2), avg_steps=round(float(avg_steps or 0.0), 2), baseline_avg_steps=round(baseline, 2), avg_pnl=round(float(avg_pnl or 0.0), 2), sparkline=sparkline))

        response.headers["Cache-Control"] = "max-age=300"
        
        run_summary = {"items": [x.model_dump() for x in items]}
        return StandardResponse(success=True, data=run_summary).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get run summary: {str(e)}")


async def _upsert_signal(session, *, priority: str, signal_type: str, source_entity_id: str, message: str, action_label: str, action_type: str, run_id: str | None = None):
    sid = hashlib.sha1(f"{priority}|{signal_type}|{source_entity_id}".encode()).hexdigest()[:24]
    if (await session.execute(select(Signal.id).where(Signal.id == sid))).scalar_one_or_none() is None:
        session.add(Signal(id=sid, priority=priority, message=message, action_label=action_label, action_type=action_type, run_id=run_id))


async def generate_signals(reference_dt: Optional[datetime] = None) -> None:
    global LAST_SIGNAL_GENERATION, LAST_SIGNAL_GENERATION_STATUS
    now = reference_dt or datetime.utcnow()
    async with get_async_session() as session:
        bad_runs = (await session.execute(select(Run).where(Run.created_at >= now - timedelta(hours=1), Run.pnl < -500))).scalars().all()
        for run in bad_runs:
            await _upsert_signal(session, priority="urgent", signal_type="large_loss", source_entity_id=str(run.id), message=f"Run {run.id} posted a large loss ({run.pnl:.2f}).", action_label="View run", action_type="view_run", run_id=str(run.id))

        constraints = int((await session.execute(select(func.count(TraceStep.id)).where(TraceStep.step_type == "constraint_violation", TraceStep.created_at >= _utc_midnight(now, 0)))).scalar() or 0)
        if constraints > 0:
            await _upsert_signal(session, priority="urgent", signal_type="constraint_violation", source_entity_id="today", message=f"{constraints} constraint violations detected today.", action_label="Flag", action_type="flag")

        low_conf = (await session.execute(select(Insight).where(Insight.confidence < 0.6, Insight.dismissed.is_(False)).limit(50))).scalars().all()
        for ins in low_conf:
            await _upsert_signal(session, priority="review", signal_type="low_confidence_insight", source_entity_id=str(ins.id), message=f"Insight {ins.id} needs more data (conf {ins.confidence:.2f}).", action_label="Reinforce", action_type="reinforce", run_id=str(ins.run_id))

        dna = (await session.execute(select(StrategyDNA).where(StrategyDNA.updated_at >= now - timedelta(hours=24)))).scalars().all()
        for row in dna:
            await _upsert_signal(session, priority="info", signal_type="dna_state_change", source_entity_id=row.rule_key, message=f"DNA segment {row.rule_key} changed state to {row.state}.", action_label="Dismiss", action_type="dismiss")

    LAST_SIGNAL_GENERATION = now
    LAST_SIGNAL_GENERATION_STATUS = "success"


async def signal_scheduler() -> None:
    global SCHEDULER_RUNNING, LAST_SIGNAL_GENERATION_STATUS
    SCHEDULER_RUNNING = True
    while True:
        try:
            await generate_signals()
        except Exception:
            LAST_SIGNAL_GENERATION_STATUS = "failed"
            pass
        await asyncio.sleep(300)


async def hourly_scoring_retry_scheduler() -> None:
    service = AgentLearningService()
    while True:
        try:
            async with get_async_session() as session:
                run_ids = await service.get_failed_runs_for_rescore(session)
            for run_id in run_ids:
                async with get_async_session() as session:
                    await service.score_run_with_retries(run_id, session)
        except Exception:
            pass
        await asyncio.sleep(3600)


@router.get("/signals")
async def get_signals(response: Response):
    try:
        async with get_async_session() as session:
            rows = (await session.execute(select(Signal).where(Signal.dismissed.is_(False)).order_by(Signal.created_at.desc()))).scalars().all()
            response.headers["Cache-Control"] = "no-store"
            data = {"items": [{"id": r.id, "priority": r.priority, "message": r.message, "action_label": r.action_label, "action_type": r.action_type, "run_id": r.run_id, "created_at": r.created_at, "dismissed": r.dismissed} for r in rows]}
            return StandardResponse(success=True, data=data).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get signals: {str(e)}")


@router.post("/signals/{signal_id}/dismiss")
async def dismiss_signal(signal_id: str):
    try:
        async with get_async_session() as session:
            row = (await session.execute(select(Signal).where(Signal.id == signal_id))).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="signal not found")
            row.dismissed = True
            await session.flush()
            return StandardResponse(success=True, data={"status": "dismissed", "id": signal_id}).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dismiss signal: {str(e)}")


@router.get("/system/health")
async def system_health():
    try:
        async with get_async_session() as session:
            feedback_jobs_pending = int((await session.execute(select(func.count(FeedbackJob.id)).where(FeedbackJob.status == "pending"))).scalar() or 0)
            feedback_jobs_failed = int((await session.execute(select(func.count(FeedbackJob.id)).where(FeedbackJob.status == "failed", FeedbackJob.created_at >= datetime.utcnow() - timedelta(hours=24)))).scalar() or 0)
            scoring_pending = int((await session.execute(select(func.count(Run.id)).where(Run.scoring_status == "pending"))).scalar() or 0)
            scoring_failed = int((await session.execute(select(func.count(Run.id)).where(Run.scoring_status == "failed"))).scalar() or 0)
            scoring_failed_last_24h = int((await session.execute(select(func.count(Run.id)).where(Run.scoring_status == "failed", Run.created_at >= datetime.utcnow() - timedelta(hours=24)))).scalar() or 0)
            scoring_abandoned_count = int((await session.execute(select(func.count(Run.id)).where(Run.scoring_abandoned_at.is_not(None)))).scalar() or 0)
            last_prompt_rebuild = (await session.execute(select(func.max(VectorMemoryRecord.created_at)).where(VectorMemoryRecord.store_type == "prompt-cache"))).scalar()
            last_successful_score_at = (await session.execute(select(func.max(Run.updated_at)).where(Run.scoring_status == "scored"))).scalar()
            oldest_pending_created_at = (await session.execute(select(func.min(Run.created_at)).where(Run.scoring_status == "pending"))).scalar()

        oldest_pending_score_age_seconds = None
        if oldest_pending_created_at is not None:
            oldest_pending_score_age_seconds = (datetime.utcnow() - oldest_pending_created_at).total_seconds()

        health_data = SystemHealth(
            feedback_jobs_pending=feedback_jobs_pending,
            feedback_jobs_failed=feedback_jobs_failed,
            scoring_pending=scoring_pending,
            scoring_failed=scoring_failed,
            scoring_failed_last_24h=scoring_failed_last_24h,
            scoring_abandoned_count=scoring_abandoned_count,
            last_signal_generation=LAST_SIGNAL_GENERATION,
            last_signal_generation_status=LAST_SIGNAL_GENERATION_STATUS,
            last_prompt_rebuild=last_prompt_rebuild,
            last_successful_score_at=last_successful_score_at,
            oldest_pending_score_age_seconds=oldest_pending_score_age_seconds,
            signal_scheduler_running=SCHEDULER_RUNNING,
        )
        
        return StandardResponse(success=True, data=health_data.model_dump()).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system health: {str(e)}")


@router.options("/signals")
@router.options("/signals/{signal_id}/dismiss")
@router.options("/system/health")
async def dashboard_options():
    return StandardResponse(success=True, data={"message": "Dashboard endpoints support GET, POST, and OPTIONS"}).model_dump()


# Generate signals function for signal scheduler
async def generate_signals(reference_dt: Optional[datetime] = None) -> None:
    global LAST_SIGNAL_GENERATION, LAST_SIGNAL_GENERATION_STATUS
    now = reference_dt or datetime.utcnow()
    async with get_async_session() as session:
        bad_runs = (await session.execute(select(Run).where(Run.created_at >= now - timedelta(hours=1), Run.pnl < -500))).scalars().all()
        for run in bad_runs:
            await _upsert_signal(session, priority="urgent", signal_type="large_loss", source_entity_id=str(run.id), message=f"Run {run.id} posted a large loss ({run.pnl:.2f}).", action_label="View run", action_type="view_run", run_id=str(run.id))
        
        constraints = int((await session.execute(select(func.count(TraceStep.id)).where(TraceStep.step_type == "constraint_violation", TraceStep.created_at >= _utc_midnight(now, 0)))).scalar() or 0)
        if constraints > 0:
            await _upsert_signal(session, priority="urgent", signal_type="constraint_violation", source_entity_id="today", message=f"{constraints} constraint violations detected today.", action_label="Flag", action_type="flag")
        
        low_conf = (await session.execute(select(Insight).where(Insight.confidence < 0.6, Insight.dismissed.is_(False)).limit(50))).scalars().all()
        for ins in low_conf:
            await _upsert_signal(session, priority="review", signal_type="low_confidence_insight", source_entity_id=str(ins.id), message=f"Insight {ins.id} needs more data (conf {ins.confidence:.2f}).", action_label="Reinforce", action_type="reinforce", run_id=str(ins.run_id))
        
        dna = (await session.execute(select(StrategyDNA).where(StrategyDNA.updated_at >= now - timedelta(hours=24)))).scalars().all()
        for row in dna:
            await _upsert_signal(session, priority="info", signal_type="dna_state_change", source_entity_id=row.rule_key, message=f"DNA segment {row.rule_key} changed state to {row.state}.", action_label="Dismiss", action_type="dismiss")
    LAST_SIGNAL_GENERATION = now
    LAST_SIGNAL_GENERATION_STATUS = "success"


async def signal_scheduler() -> None:
    global SCHEDULER_RUNNING, LAST_SIGNAL_GENERATION_STATUS
    SCHEDULER_RUNNING = True
    while True:
        try:
            await generate_signals()
        except Exception:
            LAST_SIGNAL_GENERATION_STATUS = "failed"
            pass
        await asyncio.sleep(300)


async def hourly_scoring_retry_scheduler() -> None:
    service = AgentLearningService()
    while True:
        try:
            async with get_async_session() as session:
                run_ids = await service.get_failed_runs_for_rescore(session)
            for run_id in run_ids:
                async with get_async_session() as session:
                    await service.score_run_with_retries(run_id, session)
        except Exception:
            pass
        await asyncio.sleep(3600)


async def _upsert_signal(session, priority: str, signal_type: str, source_entity_id: str, message: str, action_label: str, action_type: str, run_id: Optional[str] = None) -> None:
    existing = (await session.execute(select(Signal).where(Signal.source_entity_id == source_entity_id, Signal.signal_type == signal_type))).scalar_one_or_none()
    if existing:
        existing.priority = priority
        existing.message = message
        existing.action_label = action_label
        existing.action_type = action_type
        existing.run_id = run_id
        existing.created_at = datetime.utcnow()
    else:
        signal = Signal(
            id=str(uuid.uuid4()),
            priority=priority,
            signal_type=signal_type,
            source_entity_id=source_entity_id,
            message=message,
            action_label=action_label,
            action_type=action_type,
            run_id=run_id,
            created_at=datetime.utcnow(),
        )
        session.add(signal)
