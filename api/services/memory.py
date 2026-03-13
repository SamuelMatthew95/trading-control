from __future__ import annotations

import json
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import AgentRun


class AgentMemoryService:
    """Persist orchestrator execution traces in the database."""

    async def persist_run(self, session: AsyncSession, run_entry: Dict[str, Any]) -> AgentRun:
        record = AgentRun(
            task_id=run_entry.get("task_id", "unknown"),
            decision_json=json.dumps(run_entry.get("decision", {}), default=str),
            trace_json=json.dumps(run_entry.get("trace", []), default=str),
        )
        session.add(record)
        await session.flush()
        return record
