from __future__ import annotations

import json
from datetime import datetime
from typing import Dict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import AgentPerformance, AgentPerformanceView


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
            for agent in ["SIGNAL_AGENT", "CONSENSUS_AGENT", "RISK_AGENT", "SIZING_AGENT"]
        }

    async def record_agent_call(self, agent_name: str, success: bool, response_time: float, session: AsyncSession) -> None:
        if agent_name not in self.agent_performance:
            return
        perf = self.agent_performance[agent_name]
        perf["total_calls"] += 1
        if success:
            perf["successful_calls"] += 1
        total_calls = perf["total_calls"]
        perf["avg_response_time"] = ((perf["avg_response_time"] * (total_calls - 1)) + response_time) / total_calls

        result = await session.execute(select(AgentPerformance).where(AgentPerformance.agent_name == agent_name))
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

    async def get_agent_performance(self, agent_name: str, session: AsyncSession) -> AgentPerformanceView:
        result = await session.execute(select(AgentPerformance).where(AgentPerformance.agent_name == agent_name))
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")
        return AgentPerformanceView(
            agent_name=row.agent_name,
            total_calls=row.total_calls,
            successful_calls=row.successful_calls,
            avg_response_time=row.avg_response_time,
            accuracy_score=row.accuracy_score,
            improvement_areas=json.loads(row.improvement_areas) if row.improvement_areas else [],
        )
