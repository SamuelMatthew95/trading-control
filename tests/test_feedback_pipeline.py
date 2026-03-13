import json

import pytest

from api.core.models import AgentRun, ReinforceRequest, StrategyDNA, TraceStep, VectorMemoryRecord
from api.database import AsyncSessionLocal, init_database
from api.services.feedback import FeedbackLearningService
from multi_agent_orchestrator import ToolError, TradeTools


@pytest.mark.asyncio
async def test_feedback_reinforce_promotes_dna_and_memories():
    await init_database()
    service = FeedbackLearningService()

    async with AsyncSessionLocal() as session:
        run = AgentRun(task_id="risk:run-1", decision_json=json.dumps({"decision": "LONG"}), trace_json=json.dumps([{"type": "think"}, {"type": "do", "success": True}]))
        session.add(run)
        await session.flush()

        session.add(
            TraceStep(
                run_id=run.id,
                node_name="risk",
                tool_call="fetch_news",
                transcript="Risk step",
                is_hallucination=True,
                coach_reason="Source mismatch",
                is_starred=True,
                promoted_rule_key="risk_rule_1",
                feedback_status="pending",
            )
        )
        await session.flush()
        result = await service.reinforce(session, ReinforceRequest(run_id=run.id))

        assert result.status == "learned"
        assert result.negative_memories == 1
        assert result.few_shot_memories == 1
        assert "risk_rule_1" in result.promoted_rules

        dna = (await session.execute(StrategyDNA.__table__.select().where(StrategyDNA.rule_key == "risk_rule_1"))).first()
        assert dna is not None


@pytest.mark.asyncio
async def test_feedback_job_persistence():
    await init_database()
    service = FeedbackLearningService()

    async with AsyncSessionLocal() as session:
        run = AgentRun(task_id="consensus:run-2", decision_json="{}", trace_json="[]")
        session.add(run)
        await session.flush()

        job = await service.create_feedback_job(session, run.id)
        assert job.status == "pending"

        await service.run_feedback_job(session, job.id, ReinforceRequest(run_id=run.id))
        status = await service.get_feedback_job(session, job.id)

        assert status is not None
        assert status.status == "done"
        assert status.completed_at is not None


@pytest.mark.asyncio
async def test_memory_guard_blocks_tool():
    await init_database()

    async with AsyncSessionLocal() as session:
        probe = 'get_current_price:{"asset": "AAPL"}'
        digest = TradeTools().memory_guard._embed(probe)
        session.add(
            VectorMemoryRecord(
                store_type="negative-memory",
                run_id=999,
                node_name="sizing",
                content="avoid stale feed",
                embedding_json=json.dumps(digest),
                metadata_json=json.dumps({"reason": "Known stale price feed"}),
            )
        )
        await session.commit()

    tools = TradeTools()
    with pytest.raises(ToolError, match="skipped_by_memory_guard"):
        tools.get_current_price("AAPL")
    assert tools.guard_hits >= 1


@pytest.mark.asyncio
async def test_insight_confidence_in_response():
    await init_database()
    service = FeedbackLearningService()

    async with AsyncSessionLocal() as session:
        run = AgentRun(task_id="signal:run-3", decision_json="{}", trace_json=json.dumps([{"type": "think"}, {"type": "do"}]))
        session.add(run)
        await session.flush()
        await service.run_supervisor_pass(session)
        insights = await service.list_insights(session)

    assert insights
    assert all(hasattr(item, "confidence") for item in insights)
    assert all(hasattr(item, "needs_more_data") for item in insights)
    assert all(hasattr(item, "supporting_run_count") for item in insights)
