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


@pytest.mark.asyncio
async def test_alerts_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/alerts")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_alerts_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/alerts")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_alerts_empty_list(client: AsyncClient) -> None:
    r = await client.get("/monitoring/alerts")
    body = r.json()
    assert body[FieldName.ALERTS] == []


@pytest.mark.asyncio
async def test_system_metrics_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/system-metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_system_metrics_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/system-metrics")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_system_metrics_key_present(client: AsyncClient) -> None:
    r = await client.get("/monitoring/system-metrics")
    body = r.json()
    assert FieldName.SYSTEM_METRICS in body


@pytest.mark.asyncio
async def test_performance_metrics_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/performance-metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_performance_metrics_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/performance-metrics")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_performance_metrics_key_present(client: AsyncClient) -> None:
    r = await client.get("/monitoring/performance-metrics")
    body = r.json()
    assert FieldName.PERFORMANCE_METRICS in body


@pytest.mark.asyncio
async def test_agent_metrics_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/agent-metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_metrics_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/agent-metrics")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_agent_metrics_key_present(client: AsyncClient) -> None:
    r = await client.get("/monitoring/agent-metrics")
    body = r.json()
    assert FieldName.AGENT_METRICS in body


@pytest.mark.asyncio
async def test_data_metrics_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/data-metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_data_metrics_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/data-metrics")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_data_metrics_key_present(client: AsyncClient) -> None:
    r = await client.get("/monitoring/data-metrics")
    body = r.json()
    assert FieldName.DATA_METRICS in body


@pytest.mark.asyncio
async def test_task_metrics_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/task-metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_task_metrics_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/task-metrics")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_task_metrics_key_present(client: AsyncClient) -> None:
    r = await client.get("/monitoring/task-metrics")
    body = r.json()
    assert FieldName.TASK_METRICS in body


@pytest.mark.asyncio
async def test_summary_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/summary")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_summary_success_flag(client: AsyncClient) -> None:
    r = await client.get("/monitoring/summary")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_summary_key_present(client: AsyncClient) -> None:
    r = await client.get("/monitoring/summary")
    body = r.json()
    assert FieldName.SUMMARY in body


@pytest.mark.asyncio
async def test_summary_has_overall_status(client: AsyncClient) -> None:
    r = await client.get("/monitoring/summary")
    body = r.json()
    assert FieldName.OVERALL_STATUS in body[FieldName.SUMMARY]


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    r = await client.get("/monitoring/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_health_status_healthy(client: AsyncClient) -> None:
    r = await client.get("/monitoring/health")
    body = r.json()
    assert body[FieldName.STATUS] == "healthy"
