from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import AgentPerformance, AgentPerformanceView, Run


class AgentLearningService:
    def __init__(self):
        self.agent_performance: Dict[str, Dict] = {
            agent: {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0.0,
                "accuracy_score": 0.0,
                "improvement_areas": [],
            }
            for agent in [
                "SIGNAL_AGENT",
                "CONSENSUS_AGENT",
                "RISK_AGENT",
                "SIZING_AGENT",
            ]
        }

    async def record_agent_call(
        self,
        agent_name: str,
        success: bool,
        response_time: float,
        session: AsyncSession,
    ) -> None:
        if agent_name not in self.agent_performance:
            return
        perf = self.agent_performance[agent_name]
        perf["total_calls"] += 1
        if success:
            perf["successful_calls"] += 1
        total_calls = perf["total_calls"]
        perf["avg_response_time"] = (
            (perf["avg_response_time"] * (total_calls - 1)) + response_time
        ) / total_calls

        result = await session.execute(
            select(AgentPerformance).where(AgentPerformance.agent_name == agent_name)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = AgentPerformance(
                agent_name=agent_name,
                total_calls=perf["total_calls"],
                successful_calls=perf["successful_calls"],
                avg_response_time=perf["avg_response_time"],
                accuracy_score=perf["accuracy_score"],
                improvement_areas=json.dumps(perf["improvement_areas"]),
            )
            session.add(row)
        else:
            row.total_calls = perf["total_calls"]
            row.successful_calls = perf["successful_calls"]
            row.avg_response_time = perf["avg_response_time"]
            row.updated_at = datetime.utcnow()

    async def get_agent_performance(
        self, agent_name: str, session: AsyncSession
    ) -> AgentPerformanceView:
        result = await session.execute(
            select(AgentPerformance).where(AgentPerformance.agent_name == agent_name)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")
        return AgentPerformanceView(
            agent_name=row.agent_name,
            total_calls=row.total_calls,
            successful_calls=row.successful_calls,
            avg_response_time=row.avg_response_time,
            accuracy_score=row.accuracy_score,
            improvement_areas=(
                json.loads(row.improvement_areas) if row.improvement_areas else []
            ),
        )

    async def post_run_scoring(self, run_id: int, session: AsyncSession) -> float:
        row = (
            await session.execute(select(Run).where(Run.id == run_id))
        ).scalar_one_or_none()
        if row is None:
            return 0.0
        trace = json.loads(row.trace_json) if row.trace_json else []
        successful = sum(1 for step in trace if step.get("success", False))
        total = max(len(trace), 1)
        logical_consistency = successful / total
        goal_adherence = 1.0 if row.status == "won" else 0.4
        no_circular_reasoning = 1.0 if successful >= (total / 2) else 0.5
        score = round(
            (logical_consistency + goal_adherence + no_circular_reasoning) / 3 * 10, 2
        )
        row.reasoning_coherence_score = score
        row.scoring_status = "scored"
        return score

    async def score_run_with_retries(
        self, run_id: int, session: AsyncSession, retries: int = 3
    ) -> None:
        backoff = [2, 10, 60]
        row = (
            await session.execute(select(Run).where(Run.id == run_id))
        ).scalar_one_or_none()
        if row is None:
            return

        for attempt in range(min(retries, len(backoff))):
            row.scoring_attempt_count = int(row.scoring_attempt_count or 0) + 1
            row.last_scoring_attempt_at = datetime.utcnow()
            try:
                await self.post_run_scoring(run_id, session)
                return
            except Exception:  # noqa: BLE001
                if attempt < retries - 1:
                    await asyncio.sleep(backoff[attempt])

        row.scoring_status = "failed"

    async def get_failed_runs_for_rescore(self, session: AsyncSession) -> list[int]:
        rows = (
            (
                await session.execute(
                    select(Run.id)
                    .where(
                        Run.scoring_status == "failed",
                        Run.created_at >= datetime.utcnow() - timedelta(hours=24),
                        Run.scoring_attempt_count < 10,
                    )
                    .order_by(Run.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
