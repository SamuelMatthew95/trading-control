from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import (
    AgentRun,
    FeedbackJob,
    FeedbackJobStatusView,
    Insight,
    InsightView,
    ProposedRun,
    ReinforceRequest,
    ReinforceResponse,
    Run,
    StrategyDNA,
    TraceStep,
    VectorMemoryRecord,
)


class FeedbackLearningService:
    """Observe → Correct → Reinforce pipeline orchestration."""

    def __init__(self):
        self._lock = asyncio.Lock()

    async def stage_annotation(
        self, session: AsyncSession, annotation: Dict[str, Any]
    ) -> TraceStep:
        step = TraceStep(
            run_id=annotation["run_id"],
            node_name=annotation.get("node_name", "unknown"),
            tool_call=annotation.get("tool_call"),
            transcript=annotation.get("transcript"),
            is_hallucination=bool(annotation.get("is_hallucination", False)),
            coach_reason=annotation.get("coach_reason"),
            is_starred=bool(annotation.get("is_starred", False)),
            override_payload=(
                json.dumps(annotation.get("override_payload"))
                if annotation.get("override_payload")
                else None
            ),
            promoted_rule_key=annotation.get("promoted_rule_key"),
            feedback_status="pending",
        )
        session.add(step)
        await session.flush()
        return step

    async def create_negative_memory(
        self, session: AsyncSession, payload: Dict[str, Any]
    ) -> VectorMemoryRecord:
        content = (
            payload.get("content") or f"tool_call={payload.get('tool_call', 'n/a')}"
        )
        reason = (
            payload.get("reason") or payload.get("coach_reason") or "negative memory"
        )
        tool_name = payload.get("tool_name")
        rec = VectorMemoryRecord(
            store_type="negative-memory",
            run_id=int(payload.get("run_id", 0)),
            node_name=payload.get("node_name", "manual"),
            content=content,
            embedding_json=json.dumps(self._embed(content)),
            metadata_json=json.dumps({"reason": reason, "tool_name": tool_name}),
        )
        session.add(rec)
        await session.flush()
        return rec

    async def enqueue_reinforce_job(
        self, session: AsyncSession, task_type: str
    ) -> FeedbackJob | None:
        run = (
            await session.execute(
                select(Run)
                .where(Run.task_type == task_type)
                .order_by(Run.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        job = await self.create_feedback_job(session, run.id)
        return job

    async def create_feedback_job(
        self, session: AsyncSession, run_id: int
    ) -> FeedbackJob:
        job = FeedbackJob(id=str(uuid.uuid4()), run_id=run_id, status="pending")
        session.add(job)
        await session.flush()
        return job

    async def get_feedback_job(
        self, session: AsyncSession, job_id: str
    ) -> FeedbackJobStatusView | None:
        row = (
            await session.execute(select(FeedbackJob).where(FeedbackJob.id == job_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        return FeedbackJobStatusView(
            id=row.id,
            run_id=row.run_id,
            status=row.status,
            error=row.error,
            completed_at=row.completed_at,
        )

    async def run_feedback_job(
        self, session: AsyncSession, job_id: str, request: ReinforceRequest
    ) -> ReinforceResponse:
        job = (
            await session.execute(select(FeedbackJob).where(FeedbackJob.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            raise ValueError(f"Unknown feedback job {job_id}")

        job.status = "running"
        job.error = None
        await session.flush()

        try:
            result = await self.reinforce(session, request)
            job.status = "done"
            job.completed_at = datetime.utcnow()
            await session.flush()
            return result
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = datetime.utcnow()
            await session.flush()
            raise

    async def reinforce(
        self, session: AsyncSession, request: ReinforceRequest
    ) -> ReinforceResponse:
        async with self._lock:
            pending_steps = (
                (
                    await session.execute(
                        select(TraceStep).where(
                            TraceStep.run_id == request.run_id,
                            TraceStep.feedback_status == "pending",
                        )
                    )
                )
                .scalars()
                .all()
            )

            if not pending_steps:
                return ReinforceResponse(
                    run_id=request.run_id,
                    status="no-op",
                    negative_memories=0,
                    few_shot_memories=0,
                    promoted_rules=[],
                    dna_delta_usd=0.0,
                    prompt_cache_key="",
                )

            negative_count = await self._upsert_negative_memory(
                session, request.run_id, pending_steps
            )
            few_shot_count = await self._upsert_few_shot_memory(
                session, request.run_id, pending_steps
            )
            promoted_rules, delta_usd = await self._mutate_strategy_dna(
                session, pending_steps
            )
            prompt_cache_key = await self._rebuild_prompt_cache(session)

            for step in pending_steps:
                step.feedback_status = "learned"

            return ReinforceResponse(
                run_id=request.run_id,
                status="learned",
                negative_memories=negative_count,
                few_shot_memories=few_shot_count,
                promoted_rules=promoted_rules,
                dna_delta_usd=round(delta_usd, 2),
                prompt_cache_key=prompt_cache_key,
            )

    async def list_insights(
        self, session: AsyncSession, limit: int = 50
    ) -> List[InsightView]:
        rows = (
            (
                await session.execute(
                    select(Insight).order_by(Insight.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            InsightView(
                id=row.id,
                tag=row.tag,
                confidence=row.confidence,
                summary=row.summary,
                run_id=row.run_id,
                needs_more_data=row.confidence < 0.6,
                supporting_run_count=row.supporting_run_count or 1,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def run_supervisor_pass(
        self, session: AsyncSession, lookback_runs: int = 50
    ) -> int:
        runs = (
            (
                await session.execute(
                    select(AgentRun)
                    .order_by(AgentRun.created_at.desc())
                    .limit(lookback_runs)
                )
            )
            .scalars()
            .all()
        )
        if not runs:
            return 0

        inserted = 0
        supporting_count = min(len(runs), lookback_runs)
        for run in runs[:10]:
            trace = json.loads(run.trace_json) if run.trace_json else []
            score = self._confidence_from_trace(trace)
            tag = self._tag_from_score(score)
            summary = f"Run {run.id} shows {tag.lower()} behavior with think/do ratio {self._think_do_ratio(trace):.2f}."
            session.add(
                Insight(
                    run_id=run.id,
                    tag=tag,
                    confidence=score,
                    summary=summary,
                    payload_json=json.dumps({"trace_steps": len(trace)}),
                    supporting_run_count=supporting_count,
                )
            )
            inserted += 1
        await session.flush()
        return inserted

    async def propose_runs(self, session: AsyncSession) -> List[ProposedRun]:
        task_rows = (
            await session.execute(
                select(AgentRun.task_id, AgentRun.trace_json)
                .order_by(AgentRun.created_at.desc())
                .limit(200)
            )
        ).all()
        if not task_rows:
            return [
                ProposedRun(
                    task_type="signal",
                    reason="Low Pass^k (0%) — needs more coverage",
                    priority=1,
                    suggested_params={"timeframe": "1D"},
                ),
                ProposedRun(
                    task_type="risk",
                    reason="Recent hallucinations detected in negative memory",
                    priority=2,
                    suggested_params={"stress_test": True},
                ),
                ProposedRun(
                    task_type="sizing",
                    reason="Ghost Path delta negative versus v1.2",
                    priority=3,
                    suggested_params={"version_compare": "v1.2"},
                ),
            ]

        by_task: dict[str, dict[str, float]] = {}
        for task_id, trace_json in task_rows:
            task_type = str(task_id).split(":", 1)[0].lower()
            stats = by_task.setdefault(task_type, {"total": 0, "pass": 0})
            stats["total"] += 1
            trace = json.loads(trace_json) if trace_json else []
            if all(step.get("success", True) for step in trace):
                stats["pass"] += 1

        pass_candidate = min(
            by_task.items(),
            key=lambda item: (item[1]["pass"] / max(item[1]["total"], 1)),
        )
        pass_rate = pass_candidate[1]["pass"] / max(pass_candidate[1]["total"], 1)

        neg = (
            await session.execute(
                select(VectorMemoryRecord.node_name, func.count(VectorMemoryRecord.id))
                .where(VectorMemoryRecord.store_type == "negative-memory")
                .group_by(VectorMemoryRecord.node_name)
                .order_by(func.count(VectorMemoryRecord.id).desc())
            )
        ).first()
        neg_task = neg[0] if neg else "risk"

        ghost = (
            await session.execute(
                select(StrategyDNA.rule_key, StrategyDNA.value_delta_usd)
                .order_by(StrategyDNA.value_delta_usd.asc())
                .limit(1)
            )
        ).first()
        ghost_task = ghost[0] if ghost else "consensus"

        return [
            ProposedRun(
                task_type=pass_candidate[0],
                reason=f"Low Pass^k ({round(pass_rate * 100)}%) — needs more coverage",
                priority=1,
                suggested_params={"batch_size": 50},
            ),
            ProposedRun(
                task_type=neg_task,
                reason="Recent hallucination flags in negative memory",
                priority=2,
                suggested_params={"replay_last": 20},
            ),
            ProposedRun(
                task_type=ghost_task,
                reason="Ghost Path delta negative (current worse than v1.2)",
                priority=3,
                suggested_params={"baseline_version": "v1.2"},
            ),
        ]

    async def _upsert_negative_memory(
        self, session: AsyncSession, run_id: int, steps: Iterable[TraceStep]
    ) -> int:
        count = 0
        for step in steps:
            if not step.is_hallucination:
                continue
            content = f"tool_call={step.tool_call or 'n/a'} reason={step.coach_reason or 'missing'}"
            tool_name = (step.tool_call or "").split("(")[0] if step.tool_call else None
            session.add(
                VectorMemoryRecord(
                    store_type="negative-memory",
                    run_id=run_id,
                    node_name=step.node_name,
                    content=content,
                    embedding_json=json.dumps(self._embed(content)),
                    metadata_json=json.dumps(
                        {"reason": step.coach_reason, "tool_name": tool_name}
                    ),
                )
            )
            count += 1
        await session.flush()
        return count

    async def _upsert_few_shot_memory(
        self, session: AsyncSession, run_id: int, steps: Iterable[TraceStep]
    ) -> int:
        starred = [step for step in steps if step.is_starred]
        if not starred:
            return 0
        run = (
            await session.execute(select(AgentRun).where(AgentRun.id == run_id))
        ).scalar_one_or_none()
        transcript = (
            run.trace_json if run else json.dumps([s.transcript for s in starred])
        )
        session.add(
            VectorMemoryRecord(
                store_type="few-shot",
                run_id=run_id,
                node_name="full_trajectory",
                content=transcript,
                embedding_json=json.dumps(self._embed(transcript)),
                metadata_json=json.dumps(
                    {"starred_nodes": [s.node_name for s in starred]}
                ),
            )
        )
        await session.flush()
        return 1

    async def _mutate_strategy_dna(
        self, session: AsyncSession, steps: Iterable[TraceStep]
    ) -> tuple[list[str], float]:
        promoted: list[str] = []
        delta = 0.0
        for step in steps:
            if not step.promoted_rule_key:
                continue
            row = (
                await session.execute(
                    select(StrategyDNA).where(
                        StrategyDNA.rule_key == step.promoted_rule_key
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = StrategyDNA(
                    rule_key=step.promoted_rule_key,
                    segment_text=f"Prioritize rule {step.promoted_rule_key}",
                    is_active=True,
                    value_delta_usd=100.0,
                    last_promoted_at=datetime.utcnow(),
                )
                session.add(row)
            else:
                row.is_active = True
                row.last_promoted_at = datetime.utcnow()
                row.value_delta_usd = float(row.value_delta_usd or 0.0) + 100.0
            promoted.append(step.promoted_rule_key)
            delta += 100.0
        await session.flush()
        return promoted, delta

    async def _rebuild_prompt_cache(self, session: AsyncSession) -> str:
        active_rows = (
            (
                await session.execute(
                    select(StrategyDNA).where(StrategyDNA.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        prompt_body = (
            "\n".join(row.segment_text for row in active_rows)
            or "Base trading system prompt."
        )
        digest = hashlib.sha1(prompt_body.encode("utf-8")).hexdigest()[:12]
        key = f"prompt:dna:v{digest}"
        session.add(
            VectorMemoryRecord(
                store_type="prompt-cache",
                run_id=0,
                node_name="system",
                content=prompt_body,
                embedding_json=json.dumps(self._embed(prompt_body)),
                metadata_json=json.dumps({"cache_key": key}),
            )
        )
        await session.flush()
        return key

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [round(b / 255.0, 6) for b in digest[:16]]

    def _think_do_ratio(self, trace: List[Dict[str, Any]]) -> float:
        think = len([s for s in trace if str(s.get("type", "")).lower() == "think"])
        do = len([s for s in trace if str(s.get("type", "")).lower() == "do"])
        if do == 0:
            return float(think)
        return think / do

    def _confidence_from_trace(self, trace: List[Dict[str, Any]]) -> float:
        ratio = self._think_do_ratio(trace)
        penalty = min(0.5, abs(1.0 - ratio) * 0.2)
        base = 0.85 - penalty
        return round(max(0.1, min(base, 0.99)), 2)

    def _tag_from_score(self, score: float) -> str:
        if score >= 0.8:
            return "Promoted"
        if score >= 0.65:
            return "Learned"
        if score >= 0.6:
            return "Observation"
        return "Needs Review"
