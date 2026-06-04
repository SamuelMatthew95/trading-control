"""Tests for the feedback and performance route surfaces.

Both run against the real app in memory mode and must never 500. Feedback uses
the in-memory FeedbackService stub; performance falls back to the runtime-store
aggregate when the DB is unavailable.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName
from api.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


# --- feedback -----------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_annotation_returns_id(client: AsyncClient) -> None:
    r = await client.post("/memory/annotations", json={"run_id": "abc", "label": "good"})
    assert r.status_code == 200
    body = r.json()
    assert FieldName.ID in body
    assert body[FieldName.STATUS] == "staged"


@pytest.mark.asyncio
async def test_reinforce_flow_queues_and_fetches_job(client: AsyncClient) -> None:
    r = await client.post("/feedback/reinforce", json={"run_id": "run-1"})
    assert r.status_code == 200
    job_id = r.json()[FieldName.JOB_ID]

    r2 = await client.get(f"/feedback/reinforce/{job_id}")
    assert r2.status_code == 200
    assert r2.json()[FieldName.ID] == job_id


@pytest.mark.asyncio
async def test_reinforce_unknown_job_404(client: AsyncClient) -> None:
    r = await client.get("/feedback/reinforce/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_insights_returns_standard_response(client: AsyncClient) -> None:
    r = await client.get("/insights")
    assert r.status_code == 200
    body = r.json()
    assert body[FieldName.SUCCESS] is True
    assert FieldName.ITEMS in body[FieldName.DATA]


@pytest.mark.asyncio
async def test_blocklist_echoes_tools(client: AsyncClient) -> None:
    r = await client.post("/config/blocklist", json={"tools": ["t1", "t2"]})
    assert r.status_code == 200
    assert r.json()[FieldName.BLOCKED_TOOLS] == ["t1", "t2"]


# --- performance --------------------------------------------------------------
@pytest.mark.asyncio
async def test_statistics_memory_mode_returns_200(client: AsyncClient) -> None:
    r = await client.get("/api/statistics?force_refresh=true")
    assert r.status_code == 200
    body = r.json()
    assert FieldName.TOTAL_TRADES in body
    assert body[FieldName.SOURCE] == "in_memory"


@pytest.mark.asyncio
async def test_all_performance_returns_roster(client: AsyncClient) -> None:
    r = await client.get("/api/performance")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert len(body) > 0


@pytest.mark.asyncio
async def test_recent_runs_memory_mode_returns_200(client: AsyncClient) -> None:
    r = await client.get("/api/runs")
    assert r.status_code == 200
    body = r.json()
    assert FieldName.RUNS in body
