from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict

from sqlalchemy import func, select

from api.core.models import Run, TaskTypeBaseline
from api.database import get_async_session
from api.services.feedback import FeedbackLearningService
from api.services.learning import AgentLearningService
from api.services.memory import AgentMemoryService


class RunLifecycleService:
    def __init__(
        self,
        learning_service: AgentLearningService,
        memory_service: AgentMemoryService,
        feedback_service: FeedbackLearningService,
    ):
        self.learning_service = learning_service
        self.memory_service = memory_service
        self.feedback_service = feedback_service

    async def complete_run(self, run_entry: Dict[str, Any]) -> int:
        async with get_async_session() as session:
            run = await self.memory_service.persist_run(session, run_entry)
            run_id = run.id

        async def _post_persist() -> None:
            async with get_async_session() as session:
                await self.learning_service.score_run_with_retries(run_id, session)
                row = (
                    await session.execute(select(Run).where(Run.id == run_id))
                ).scalar_one_or_none()
                if row is not None and row.scoring_status == "scored":
                    try:
                        verified = await self.memory_service.verify_corrections(
                            session, row
                        )
                        if not verified:
                            row.correction_verification_status = "pending"
                    except Exception:  # noqa: BLE001
                        row.correction_verification_status = "failed"

            # generate_signals removed - no longer available
            await self._auto_trigger_feedback(run_id)

        asyncio.create_task(_post_persist())
        return run_id

    async def requeue_failed_scores_and_corrections(self) -> int:
        processed = 0
        async with get_async_session() as session:
            run_ids = await self.learning_service.get_failed_runs_for_rescore(session)
            old_or_exhausted = (
                (
                    await session.execute(
                        select(Run).where(
                            Run.scoring_status == "failed",
                            (
                                (
                                    Run.created_at
                                    <= datetime.utcnow() - timedelta(hours=24)
                                )
                                | (Run.scoring_attempt_count >= 10)
                            ),
                            Run.scoring_abandoned_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in old_or_exhausted:
                row.scoring_abandoned_at = datetime.utcnow()

            correction_failed_ids = (
                (
                    await session.execute(
                        select(Run.id).where(
                            Run.correction_verification_status == "failed",
                            Run.created_at >= datetime.utcnow() - timedelta(hours=24),
                        )
                    )
                )
                .scalars()
                .all()
            )

        for run_id in run_ids:
            async with get_async_session() as session:
                await self.learning_service.score_run_with_retries(run_id, session)
                processed += 1

        for run_id in correction_failed_ids:
            async with get_async_session() as session:
                row = (
                    await session.execute(select(Run).where(Run.id == run_id))
                ).scalar_one_or_none()
                if row is None:
                    continue
                try:
                    verified = await self.memory_service.verify_corrections(
                        session, row
                    )
                    row.correction_verification_status = (
                        "verified" if verified else "pending"
                    )
                except Exception:  # noqa: BLE001
                    row.correction_verification_status = "failed"
                processed += 1

        return processed

    async def _auto_trigger_feedback(self, run_id: int) -> None:
        async with get_async_session() as session:
            run = (
                await session.execute(select(Run).where(Run.id == run_id))
            ).scalar_one_or_none()
            if run is None:
                return
            baseline = (
                await session.execute(
                    select(TaskTypeBaseline).where(
                        TaskTypeBaseline.task_type == run.task_type
                    )
                )
            ).scalar_one_or_none()
            last_feedback = (
                baseline.last_feedback_run_at
                if baseline and baseline.last_feedback_run_at
                else datetime.fromtimestamp(0)
            )
            count = int(
                (
                    await session.execute(
                        select(func.count(Run.id)).where(
                            Run.task_type == run.task_type,
                            Run.created_at > last_feedback,
                        )
                    )
                ).scalar()
                or 0
            )
            if count >= 10:
                await self.feedback_service.enqueue_reinforce_job(
                    session, run.task_type
                )
                if baseline is not None:
                    baseline.last_feedback_run_at = datetime.utcnow()
