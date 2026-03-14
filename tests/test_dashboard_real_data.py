from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from api.core.models import (Insight, Run, Signal, TaskTypeBaseline, TraceStep,
                             VectorMemoryRecord)
from api.database import AsyncSessionLocal, init_database
from api.main import app
from api.routes import dashboard, signals, system
from tests.conftest import TEST_REFERENCE_DT


@pytest_asyncio.fixture
async def seeded_db():
    await init_database()
    async with AsyncSessionLocal() as session:
        for model in [TraceStep, Signal, Insight, Run, TaskTypeBaseline]:
            await session.execute(delete(model))
            await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        for model in [TraceStep, Signal, Insight, Run, TaskTypeBaseline]:
            await session.execute(delete(model))
            await session.commit()


@pytest_asyncio.fixture
async def api_client(seeded_db):
    await app.router.startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        yield client
    await app.router.shutdown()


@pytest.mark.asyncio
async def test_pnl_aggregation(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        for v in [120.0, 340.0, 80.0, 210.0, 95.0]:
            session.add(
                Run(
                    task_id=f"won-{v}",
                    task_type="pharma earnings",
                    status="won",
                    pnl=v,
                    step_count=4,
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now,
                )
            )
        for v in [-50.0, -30.0]:
            session.add(
                Run(
                    task_id=f"fail-{v}",
                    task_type="pharma earnings",
                    status="failed",
                    pnl=v,
                    step_count=4,
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now,
                )
            )
        await session.flush()
        for c in [4.5, 5.0, 5.0]:
            session.add(
                TraceStep(run_id=1, node_name="n", token_cost_usd=c, created_at=now)
            )
        await session.commit()

    res = await api_client.get(
        "/dashboard/pnl", params={"reference_dt": now.isoformat()}
    )
    body = res.json()
    assert body["data"]["total_pnl"] == 765.0
    assert body["data"]["execution_cost"] == 14.5
    assert body["data"]["net_alpha"] == 750.5


@pytest.mark.asyncio
async def test_passk_trend_improving(api_client):
    now = TEST_REFERENCE_DT
    rates = [0.55, 0.60, 0.65, 0.70, 0.75]
    async with AsyncSessionLocal() as session:
        for i, rate in enumerate(rates):
            day = now - timedelta(days=4 - i)
            wins = int(rate * 20)
            for j in range(20):
                session.add(
                    Run(
                        task_id=f"imp-{i}-{j}",
                        task_type="mid-cap tech sentiment",
                        status="won" if j < wins else "failed",
                        pnl=10.0,
                        step_count=4,
                        decision_json="{}",
                        trace_json="[]",
                        created_at=day,
                    )
                )
        await session.commit()
    res = await api_client.get(
        "/dashboard/learning-velocity", params={"reference_dt": now.isoformat()}
    )
    assert res.json()["data"]["passk_trend"] == "improving"


@pytest.mark.asyncio
async def test_passk_trend_regressing(api_client):
    now = TEST_REFERENCE_DT
    rates = [0.75, 0.70, 0.60, 0.55, 0.45]
    async with AsyncSessionLocal() as session:
        for i, rate in enumerate(rates):
            day = now - timedelta(days=4 - i)
            wins = int(rate * 20)
            for j in range(20):
                session.add(
                    Run(
                        task_id=f"reg-{i}-{j}",
                        task_type="mid-cap tech sentiment",
                        status="won" if j < wins else "failed",
                        pnl=10.0,
                        step_count=4,
                        decision_json="{}",
                        trace_json="[]",
                        created_at=day,
                    )
                )
        await session.commit()
    res = await api_client.get(
        "/dashboard/learning-velocity", params={"reference_dt": now.isoformat()}
    )
    assert res.json()["data"]["passk_trend"] == "regressing"


@pytest.mark.asyncio
async def test_tool_thrashing_detection(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        run = Run(
            task_id="thrash",
            task_type="x",
            status="won",
            pnl=1,
            step_count=5,
            decision_json="{}",
            trace_json="[]",
            created_at=now,
        )
        session.add(run)
        await session.flush()
        for tool in ["a", "search", "search", "search", "b"]:
            session.add(
                TraceStep(
                    run_id=run.id,
                    node_name="n",
                    tool_name=tool,
                    step_type="step",
                    created_at=now,
                )
            )
        await session.commit()
    res = await api_client.get(
        "/dashboard/health-signals", params={"reference_dt": now.isoformat()}
    )
    item = next(
        x for x in res.json()["data"]["items"] if x["key"] == "tool_thrashing_rate"
    )
    assert float(item["value"].replace("%", "")) > 0


@pytest.mark.asyncio
async def test_memory_guard_effectiveness(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        pnls = [1, 2, 3, -1]
        for i, pnl in enumerate(pnls):
            run = Run(
                task_id=f"g{i}",
                task_type="x",
                status="won" if pnl > 0 else "failed",
                pnl=pnl,
                step_count=1,
                decision_json="{}",
                trace_json="[]",
                created_at=now,
            )
            session.add(run)
            await session.flush()
            session.add(
                TraceStep(
                    run_id=run.id,
                    node_name="n",
                    step_type="skipped_by_memory_guard",
                    created_at=now,
                )
            )
        await session.commit()
    res = await api_client.get(
        "/dashboard/learning-velocity", params={"reference_dt": now.isoformat()}
    )
    assert res.json()["data"]["memory_guard_effectiveness_pct"] == 75.0


@pytest.mark.asyncio
async def test_signal_auto_generation(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        session.add(
            Run(
                task_id="loss",
                task_type="x",
                status="failed",
                pnl=-600,
                step_count=1,
                decision_json="{}",
                trace_json="[]",
                created_at=now - timedelta(minutes=30),
            )
        )
        await session.commit()
    await generate_signals(reference_dt=now)
    res = await api_client.get("/signals")
    assert any(
        x["priority"] == "urgent" and "loss" in x["message"].lower()
        for x in res.json()["data"]["items"]
    )


@pytest.mark.asyncio
async def test_signal_dismiss(api_client):
    async with AsyncSessionLocal() as session:
        session.add(
            Signal(
                id="sig-x",
                priority="info",
                message="m",
                action_label="Dismiss",
                action_type="dismiss",
                run_id=None,
                dismissed=False,
            )
        )
        await session.commit()
    await api_client.post("/signals/sig-x/dismiss")
    res = await api_client.get("/signals")
    assert all(x["id"] != "sig-x" for x in res.json()["data"]["items"])


@pytest.mark.asyncio
async def test_run_summary_sparkline_gap_fill(api_client):
    now = TEST_REFERENCE_DT
    days = [0, 2, 4]
    async with AsyncSessionLocal() as session:
        for i, d in enumerate(days):
            session.add(
                Run(
                    task_id=f"s{i}",
                    task_type="Pharma earnings",
                    status="won",
                    pnl=100,
                    step_count=4,
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now - timedelta(days=6 - d),
                )
            )
        await session.commit()
    res = await api_client.get(
        "/dashboard/run-summary", params={"reference_dt": now.isoformat()}
    )
    row = res.json()["data"]["items"][0]
    assert len(row["sparkline"]) == 7
    assert (
        row["sparkline"][1] == 0.0
        and row["sparkline"][3] == 0.0
        and row["sparkline"][5] == 0.0
        and row["sparkline"][6] == 0.0
    )


@pytest.mark.asyncio
async def test_insight_confidence_fields(api_client):
    async with AsyncSessionLocal() as session:
        session.add(
            Insight(
                run_id=1,
                tag="Learned",
                confidence=0.8,
                summary="ok",
                supporting_run_count=2,
            )
        )
        session.add(
            Insight(
                run_id=2,
                tag="Needs Review",
                confidence=0.4,
                summary="bad",
                supporting_run_count=1,
            )
        )
        await session.commit()
    res = await api_client.get("/insights")
    items = res.json()["data"]["items"]
    assert all(
        "confidence" in i and "needs_more_data" in i and "supporting_run_count" in i
        for i in items
    )
    low = [i for i in items if i["confidence"] == 0.4][0]
    assert low["needs_more_data"] is True


@pytest.mark.asyncio
async def test_dashboard_pnl_today_isolation(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        session.add(
            Run(
                task_id="old",
                task_type="x",
                status="won",
                pnl=500,
                step_count=1,
                decision_json="{}",
                trace_json="[]",
                created_at=now - timedelta(days=2),
            )
        )
        session.add(
            Run(
                task_id="new",
                task_type="x",
                status="won",
                pnl=120,
                step_count=1,
                decision_json="{}",
                trace_json="[]",
                created_at=now - timedelta(hours=1),
            )
        )
        await session.commit()
    res = await api_client.get(
        "/dashboard/pnl", params={"reference_dt": now.isoformat()}
    )
    assert res.json()["data"]["pnl_today"] == 120.0
    assert res.json()["data"]["total_pnl"] == 620.0


@pytest.mark.asyncio
async def test_empty_database_returns_zeros(api_client):
    now = TEST_REFERENCE_DT
    assert (
        await api_client.get("/dashboard/pnl", params={"reference_dt": now.isoformat()})
    ).status_code == 200
    assert (
        await api_client.get(
            "/dashboard/learning-velocity", params={"reference_dt": now.isoformat()}
        )
    ).status_code == 200
    assert (
        await api_client.get(
            "/dashboard/health-signals", params={"reference_dt": now.isoformat()}
        )
    ).status_code == 200
    assert (
        await api_client.get(
            "/dashboard/run-summary", params={"reference_dt": now.isoformat()}
        )
    ).status_code == 200
    assert (await api_client.get("/signals")).status_code == 200


@pytest.mark.asyncio
async def test_passk_trend_with_insufficient_data(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        for d in [1, 0]:
            session.add(
                Run(
                    task_id=f"i{d}",
                    task_type="x",
                    status="won",
                    pnl=1,
                    step_count=1,
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now - timedelta(days=d),
                )
            )
        await session.commit()
    res = await api_client.get(
        "/dashboard/learning-velocity", params={"reference_dt": now.isoformat()}
    )
    body = res.json()
    assert body["data"]["passk_trend"] in {"plateauing", "improving", "regressing"}
    assert len([x for x in body["data"]["passk_series"] if x is not None]) == 2


@pytest.mark.asyncio
async def test_signal_deduplication(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        session.add(
            Run(
                task_id="loss2",
                task_type="x",
                status="failed",
                pnl=-600,
                step_count=1,
                decision_json="{}",
                trace_json="[]",
                created_at=now - timedelta(minutes=30),
            )
        )
        await session.commit()
    await generate_signals(reference_dt=now)
    await generate_signals(reference_dt=now)
    rows1 = (await api_client.get("/signals")).json()["data"]["items"]
    assert len([x for x in rows1 if "large loss" in x["message"]]) == 1


@pytest.mark.asyncio
async def test_baseline_slippage_not_overwritten(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        session.add(
            TaskTypeBaseline(task_type="pharma_earnings", baseline_slippage=0.15)
        )
        session.add(
            Run(
                task_id="b1",
                task_type="pharma_earnings",
                status="won",
                pnl=1,
                step_count=1,
                actual_slippage=0.15,
                decision_json="{}",
                trace_json="[]",
                created_at=now - timedelta(days=1),
            )
        )
        session.add(
            Run(
                task_id="b2",
                task_type="pharma_earnings",
                status="won",
                pnl=1,
                step_count=1,
                actual_slippage=0.08,
                decision_json="{}",
                trace_json="[]",
                created_at=now,
            )
        )
        await session.commit()
    async with AsyncSessionLocal() as session:
        baseline = (
            await session.execute(
                select(TaskTypeBaseline).where(
                    TaskTypeBaseline.task_type == "pharma_earnings"
                )
            )
        ).scalar_one()
        assert baseline.baseline_slippage == 0.15


@pytest.mark.asyncio
async def test_run_summary_task_type_filter(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        for i in range(3):
            session.add(
                Run(
                    task_id=f"p{i}",
                    task_type="pharma_earnings",
                    status="won",
                    pnl=1,
                    step_count=1,
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now,
                )
            )
        for i in range(2):
            session.add(
                Run(
                    task_id=f"t{i}",
                    task_type="tech_sentiment",
                    status="won",
                    pnl=1,
                    step_count=1,
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now,
                )
            )
        await session.commit()
    rows = (
        await api_client.get(
            "/dashboard/run-summary", params={"reference_dt": now.isoformat()}
        )
    ).json()["data"]["items"]
    counts = {r["task_slug"]: r["runs_7d"] for r in rows}
    assert counts["pharma_earnings"] == 3
    assert counts["tech_sentiment"] == 2


@pytest.mark.asyncio
async def test_system_health_returns_200_on_empty_db(api_client):
    res = await api_client.get("/system/health")
    body = res.json()
    assert res.status_code == 200
    assert body["data"]["feedback_jobs_pending"] == 0
    assert body["data"]["feedback_jobs_failed"] == 0
    assert body["data"]["scoring_pending"] == 0
    assert body["data"]["scoring_failed"] == 0


@pytest.mark.asyncio
async def test_scoring_lag_warning_suppressed_on_small_dataset(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        for i in range(3):
            session.add(
                Run(
                    task_id=f"sf{i}",
                    task_type="x",
                    status="won",
                    pnl=1,
                    step_count=1,
                    scoring_status="failed",
                    decision_json="{}",
                    trace_json="[]",
                    created_at=now,
                )
            )
        await session.commit()
    res = await api_client.get(
        "/dashboard/learning-velocity", params={"reference_dt": now.isoformat()}
    )
    assert res.json()["data"]["scoring_lag_warning"] is False


@pytest.mark.asyncio
async def test_system_health_oldest_pending_score(api_client):
    now = TEST_REFERENCE_DT
    async with AsyncSessionLocal() as session:
        session.add(
            Run(
                task_id="pending-old",
                task_type="x",
                status="won",
                pnl=1,
                step_count=1,
                scoring_status="pending",
                decision_json="{}",
                trace_json="[]",
                created_at=now - timedelta(seconds=400),
            )
        )
        await session.commit()
    body = (await api_client.get("/system/health")).json()
    assert body["data"]["oldest_pending_score_age_seconds"] is not None
    assert body["data"]["oldest_pending_score_age_seconds"] >= 400


@pytest.mark.asyncio
async def test_baseline_upsert_is_idempotent(seeded_db):
    from api.services.memory import AgentMemoryService

    svc = AgentMemoryService()
    async with AsyncSessionLocal() as session:
        await svc.persist_run(
            session,
            {
                "task_id": "pharma_earnings:1",
                "decision": {"DECISION": "LONG"},
                "trace": [],
                "actual_slippage": 0.15,
            },
        )
        await svc.persist_run(
            session,
            {
                "task_id": "pharma_earnings:2",
                "decision": {"DECISION": "LONG"},
                "trace": [],
                "actual_slippage": 0.08,
            },
        )
        await svc.persist_run(
            session,
            {
                "task_id": "pharma_earnings:3",
                "decision": {"DECISION": "LONG"},
                "trace": [],
                "actual_slippage": 0.01,
            },
        )
        rows = (
            (
                await session.execute(
                    select(TaskTypeBaseline).where(
                        TaskTypeBaseline.task_type == "pharma_earnings"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].baseline_slippage == 0.15


@pytest.mark.asyncio
async def test_correction_verified_after_successful_run(seeded_db):
    from api.services.memory import AgentMemoryService

    svc = AgentMemoryService()
    async with AsyncSessionLocal() as session:
        session.add(
            VectorMemoryRecord(
                store_type="negative-memory",
                run_id=1,
                node_name="pharma_earnings",
                content="bad tool",
                embedding_json="[]",
            )
        )
        run = Run(
            task_id="pharma_earnings:ok",
            task_type="pharma_earnings",
            status="won",
            pnl=100,
            step_count=1,
            scoring_status="scored",
            decision_json="{}",
            trace_json="[]",
        )
        session.add(run)
        await session.flush()
        await svc.verify_corrections(session, run)
        row = (
            await session.execute(
                select(VectorMemoryRecord).where(
                    VectorMemoryRecord.node_name == "pharma_earnings"
                )
            )
        ).scalar_one()
        assert row.correction_verified_at is not None
