"""GET /llm/health surfaces durable Redis counters alongside the ring buffer."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest_asyncio.fixture
async def store_with_fakeredis(fake_redis):
    previous = get_redis_store()
    set_redis_store(RedisStore(fake_redis))
    try:
        yield get_redis_store()
    finally:
        set_redis_store(previous)


@pytest.mark.asyncio
async def test_llm_health_empty_when_no_redis_writes(
    client: AsyncClient, store_with_fakeredis
) -> None:
    r = await client.get("/llm/health")
    assert r.status_code == 200
    # redis_metrics is always present (may be empty dict if nothing recorded)
    assert "redis_metrics" in r.json()


@pytest.mark.asyncio
async def test_llm_health_surfaces_redis_counters(
    client: AsyncClient, store_with_fakeredis
) -> None:
    await store_with_fakeredis.record_llm_call(outcome="success", latency_ms=42.0)
    await store_with_fakeredis.record_llm_call(outcome="rate_limit")
    await store_with_fakeredis.record_llm_call(outcome="timeout")

    r = await client.get("/llm/health")
    assert r.status_code == 200
    body = r.json()
    rm = body["redis_metrics"]
    assert rm["total_calls"] == 3
    assert rm["successes"] == 1
    assert rm["rate_limits"] == 1
    assert rm["timeouts"] == 1
    assert rm["last_latency_ms"] == 42


@pytest.mark.asyncio
async def test_llm_health_no_redis_store_returns_empty_block(client: AsyncClient) -> None:
    previous = get_redis_store()
    set_redis_store(None)
    try:
        r = await client.get("/llm/health")
        assert r.status_code == 200
        assert r.json()["redis_metrics"] == {}
    finally:
        set_redis_store(previous)
