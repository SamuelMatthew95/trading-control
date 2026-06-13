"""GET /health must expose shared Redis pool stats (saturation visibility).

The 2026-06 pool-starvation incident ("ConnectionError: No connection
available." across unrelated consumers) was invisible for hours because
nothing surfaced pool utilization. redis_pool_stats() reads pure in-process
counters — no Redis I/O — so /health can show ``in_use == max_connections``
(the starvation signature) even while actual Redis commands are stalling on
the saturated pool.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import api.redis_client as redis_client_module
from api.constants import FieldName
from api.main import app
from api.redis_client import _build_pool
from api.routes import health as health_module


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest.fixture
def past_grace_period(monkeypatch):
    """Force the 60s startup grace check to pass."""
    monkeypatch.setattr(
        health_module,
        "PROCESS_START_TIME",
        health_module.PROCESS_START_TIME.replace(year=2020),
    )


@pytest.mark.asyncio
async def test_health_includes_redis_pool_stats(
    client: AsyncClient, past_grace_period, monkeypatch
) -> None:
    pool = _build_pool("redis://localhost:6379/0")
    monkeypatch.setattr(redis_client_module, "_redis_pool", pool)

    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()

    pool_stats = body[FieldName.REDIS_POOL]
    assert pool_stats[FieldName.MAX_CONNECTIONS] == pool.max_connections
    assert pool_stats[FieldName.IN_USE_CONNECTIONS] == 0
    assert pool_stats[FieldName.IDLE_CONNECTIONS] == 0
    assert pool_stats[FieldName.SATURATED] is False


@pytest.mark.asyncio
async def test_health_redis_pool_null_before_pool_exists(
    client: AsyncClient, past_grace_period, monkeypatch
) -> None:
    """Before get_redis() builds the pool, /health degrades to null — never 500s."""
    monkeypatch.setattr(redis_client_module, "_redis_pool", None)

    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()[FieldName.REDIS_POOL] is None
