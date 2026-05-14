"""REST route tests for /decisions and /decisions/stats."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName
from api.main import app
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest_asyncio.fixture
async def store_with_fakeredis(fake_redis):
    previous = get_redis_store()
    store = RedisStore(fake_redis)
    set_redis_store(store)
    try:
        yield store
    finally:
        set_redis_store(previous)


@pytest.mark.asyncio
async def test_get_decisions_empty(client: AsyncClient, store_with_fakeredis) -> None:
    r = await client.get("/decisions")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_decisions_returns_newest_first(
    client: AsyncClient, store_with_fakeredis
) -> None:
    await store_with_fakeredis.push_decision({FieldName.ACTION: "buy", FieldName.SYMBOL: "BTC/USD"})
    await store_with_fakeredis.push_decision(
        {FieldName.ACTION: "sell", FieldName.SYMBOL: "ETH/USD"}
    )
    r = await client.get("/decisions")
    items = r.json()
    assert len(items) == 2
    assert items[0][FieldName.ACTION] == "sell"
    assert items[1][FieldName.ACTION] == "buy"


@pytest.mark.asyncio
async def test_get_decisions_filter_by_action(client: AsyncClient, store_with_fakeredis) -> None:
    for action in ("buy", "sell", "hold", "buy"):
        await store_with_fakeredis.push_decision(
            {FieldName.ACTION: action, FieldName.SYMBOL: "BTC/USD"}
        )
    r = await client.get("/decisions?action=buy")
    items = r.json()
    assert len(items) == 2
    assert {d[FieldName.ACTION] for d in items} == {"buy"}


@pytest.mark.asyncio
async def test_get_decisions_rejects_invalid_action(
    client: AsyncClient, store_with_fakeredis
) -> None:
    r = await client.get("/decisions?action=reject")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_decisions_rejects_invalid_limit(
    client: AsyncClient, store_with_fakeredis
) -> None:
    assert (await client.get("/decisions?limit=0")).status_code == 422
    assert (await client.get("/decisions?limit=10000")).status_code == 422


@pytest.mark.asyncio
async def test_decision_stats_empty(client: AsyncClient, store_with_fakeredis) -> None:
    r = await client.get("/decisions/stats")
    assert r.status_code == 200
    assert r.json() == {
        "total": 0,
        "last_hour": {"buys": 0, "sells": 0, "holds": 0},
        "last_decision": None,
    }


@pytest.mark.asyncio
async def test_decision_stats_aggregates_actions(client: AsyncClient, store_with_fakeredis) -> None:
    for action in ("buy", "buy", "sell", "hold", "hold", "hold"):
        await store_with_fakeredis.push_decision(
            {FieldName.ACTION: action, FieldName.SYMBOL: "BTC/USD"}
        )
    r = await client.get("/decisions/stats")
    body = r.json()
    assert body["total"] == 6
    assert body["last_hour"] == {"buys": 2, "sells": 1, "holds": 3}
    assert body["last_decision"][FieldName.ACTION] == "hold"


@pytest.mark.asyncio
async def test_decisions_empty_when_store_uninitialised(client: AsyncClient) -> None:
    previous = get_redis_store()
    set_redis_store(None)
    try:
        assert (await client.get("/decisions")).json() == []
        assert (await client.get("/decisions/stats")).json() == {
            "total": 0,
            "last_hour": {"buys": 0, "sells": 0, "holds": 0},
            "last_decision": None,
        }
    finally:
        set_redis_store(previous)


@pytest.mark.asyncio
async def test_decisions_route_under_api_prefix(client: AsyncClient, store_with_fakeredis) -> None:
    await store_with_fakeredis.push_decision({FieldName.ACTION: "buy"})
    r = await client.get("/api/decisions")
    assert r.status_code == 200
    assert len(r.json()) == 1
