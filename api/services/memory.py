from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import (
    AgentRun,
    Run,
    TaskTypeBaseline,
    TraceStep,
    VectorMemoryRecord,
)

LEGACY_AGENT_RUNS_WRITE = (
    os.getenv("LEGACY_AGENT_RUNS_WRITE", "false").lower() == "true"
)


class AgentMemoryService:
    """Persist orchestrator execution traces in the database."""

    async def persist_run(
        self, session: AsyncSession, run_entry: Dict[str, Any]
    ) -> Run:
        decision = run_entry.get("decision", {})
        trace = run_entry.get("trace", [])
        task_id = run_entry.get("task_id", "unknown")
        task_type = str(task_id).split(":", 1)[0]

        if LEGACY_AGENT_RUNS_WRITE:
            # DEPRECATED: remove once confirmed no queries read from agent_runs.
            legacy = AgentRun(
                task_id=task_id,
                decision_json=json.dumps(decision, default=str),
                trace_json=json.dumps(trace, default=str),
            )
            session.add(legacy)
            await session.flush()

        step_token_cost = sum(
            float(step.get("token_cost_usd", 0.0) or 0.0) for step in trace
        )
        run_token_cost = (
            float(run_entry.get("token_cost_usd", 0.0) or 0.0) + step_token_cost
        )
        actual_slippage = float(
            run_entry.get("actual_slippage", decision.get("actual_slippage", 0.0))
            or 0.0
        )

        await session.execute(
            text(
                """
                INSERT INTO task_type_baselines (task_type, baseline_slippage, established_at)
                VALUES (:task_type, :baseline_slippage, :established_at)
                ON CONFLICT(task_type) DO NOTHING
                """
            ),
            {
                "task_type": task_type,
                "baseline_slippage": actual_slippage,
                "established_at": datetime.utcnow(),
            },
        )

        run = Run(
            task_id=task_id,
            task_type=task_type,
            status="won" if decision.get("DECISION") in {"LONG", "SHORT"} else "failed",
            pnl=float(run_entry.get("pnl", decision.get("pnl", 0.0)) or 0.0),
            step_count=len(trace),
            token_cost_usd=run_token_cost,
            actual_slippage=actual_slippage,
            reasoning_coherence_score=run_entry.get("reasoning_coherence_score"),
            scoring_status="pending",
            correction_verification_status="pending",
            decision_json=json.dumps(decision, default=str),
            trace_json=json.dumps(trace, default=str),
        )
        session.add(run)
        await session.flush()

        for step in trace:
            session.add(
                TraceStep(
                    run_id=run.id,
                    node_name=step.get("agent_name", "unknown"),
                    tool_call=json.dumps(step.get("input_data", {}), default=str),
                    transcript=json.dumps(step.get("output_data", {}), default=str),
                    step_type="error" if not step.get("success", True) else "step",
                    tool_name=step.get("tool_name") or step.get("agent_name"),
                    tokens_used=int(step.get("tokens_used", 0) or 0),
                    context_limit=int(step.get("context_limit", 0) or 0),
                    token_cost_usd=float(step.get("token_cost_usd", 0.0) or 0.0),
                )
            )
        await session.flush()
        return run

    async def verify_corrections(self, session: AsyncSession, run: Run) -> bool:
        if run.status != "won":
            return False

        guard_tools = set(
            (
                await session.execute(
                    select(TraceStep.tool_name).where(
                        TraceStep.run_id == run.id,
                        TraceStep.step_type == "skipped_by_memory_guard",
                    )
                )
            )
            .scalars()
            .all()
        )
        negatives = (
            (
                await session.execute(
                    select(VectorMemoryRecord).where(
                        VectorMemoryRecord.store_type == "negative-memory",
                        VectorMemoryRecord.correction_verified_at.is_(None),
                        VectorMemoryRecord.node_name == run.task_type,
                    )
                )
            )
            .scalars()
            .all()
        )

        updated = False
        for rec in negatives:
            metadata = json.loads(rec.metadata_json) if rec.metadata_json else {}
            tool_name = metadata.get("tool_name")
            if not guard_tools:
                rec.correction_verified_at = datetime.utcnow()
                updated = True
            elif tool_name and tool_name in guard_tools:
                rec.correction_verified_at = datetime.utcnow()
                updated = True

        if updated:
            run.correction_verification_status = "verified"
        return updated
