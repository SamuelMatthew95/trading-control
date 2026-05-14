"""REST route tests for /notifications, /notifications/unread-count, .../{id}/read.

These tests bind the global RedisStore singleton to a fakeredis instance and
hit the FastAPI app via httpx. They verify the wire contract the dashboard
relies on for catch-up after a WebSocket disconnect.
"""

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
    """Install a fakeredis-backed RedisStore as the process singleton."""
    previous = get_redis_store()
    store = RedisStore(fake_redis)
    set_redis_store(store)
    try:
        yield store
    finally:
        set_redis_store(previous)


@pytest.mark.asyncio
async def test_get_notifications_empty(client: AsyncClient, store_with_fakeredis) -> None:
    r = await client.get("/notifications")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_notifications_returns_pushed_items(
    client: AsyncClient, store_with_fakeredis
) -> None:
    await store_with_fakeredis.push_notification({"id": "n-1", "title": "first"})
    await store_with_fakeredis.push_notification({"id": "n-2", "title": "second"})

    r = await client.get("/notifications")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # Newest first
    assert items[0]["id"] == "n-2"
    assert items[1]["id"] == "n-1"


@pytest.mark.asyncio
async def test_get_notifications_respects_limit(client: AsyncClient, store_with_fakeredis) -> None:
    for i in range(20):
        await store_with_fakeredis.push_notification({"id": f"n-{i}", "title": "x"})

    r = await client.get("/notifications?limit=5")
    assert r.status_code == 200
    assert len(r.json()) == 5


@pytest.mark.asyncio
async def test_get_notifications_rejects_invalid_limit(
    client: AsyncClient, store_with_fakeredis
) -> None:
    r = await client.get("/notifications?limit=0")
    assert r.status_code == 422
    r = await client.get("/notifications?limit=9999")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unread_count_starts_at_zero(client: AsyncClient, store_with_fakeredis) -> None:
    r = await client.get("/notifications/unread-count")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


@pytest.mark.asyncio
async def test_unread_count_increments_with_each_push(
    client: AsyncClient, store_with_fakeredis
) -> None:
    await store_with_fakeredis.push_notification({"id": "a"})
    await store_with_fakeredis.push_notification({"id": "b"})
    r = await client.get("/notifications/unread-count")
    assert r.json() == {"count": 2}


@pytest.mark.asyncio
async def test_mark_read_decrements_count(client: AsyncClient, store_with_fakeredis) -> None:
    await store_with_fakeredis.push_notification({"id": "a"})
    await store_with_fakeredis.push_notification({"id": "b"})

    r = await client.post("/notifications/a/read")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": "a"}

    r = await client.get("/notifications/unread-count")
    assert r.json() == {"count": 1}


@pytest.mark.asyncio
async def test_mark_read_idempotent_via_http(client: AsyncClient, store_with_fakeredis) -> None:
    await store_with_fakeredis.push_notification({"id": "a"})
    assert (await client.post("/notifications/a/read")).status_code == 200
    assert (await client.post("/notifications/a/read")).status_code == 200
    r = await client.get("/notifications/unread-count")
    assert r.json() == {"count": 0}


@pytest.mark.asyncio
async def test_notifications_empty_when_store_uninitialised(client: AsyncClient) -> None:
    """If RedisStore singleton was never installed, endpoints degrade gracefully."""
    previous = get_redis_store()
    set_redis_store(None)
    try:
        assert (await client.get("/notifications")).json() == []
        assert (await client.get("/notifications/unread-count")).json() == {"count": 0}
        r = await client.post("/notifications/x/read")
        assert r.status_code == 503
    finally:
        set_redis_store(previous)


@pytest.mark.asyncio
async def test_notifications_route_under_api_prefix(
    client: AsyncClient, store_with_fakeredis
) -> None:
    """Mounted at both root and /api — verify the /api form works too."""
    await store_with_fakeredis.push_notification({"id": "abc", "title": "hi"})
    r = await client.get("/api/notifications")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "abc"


@pytest.mark.asyncio
async def test_mark_read_handles_slash_in_id(client: AsyncClient, store_with_fakeredis) -> None:
    """Trade notification ids embed the symbol (e.g. trade:buy:BTC/USD:<trace>)
    — the ``:path`` converter on the route must capture the slash."""
    slash_id = "trade:buy:BTC/USD:trace-123"
    await store_with_fakeredis.push_notification({"id": slash_id, "title": "x"})

    r = await client.post(f"/notifications/{slash_id}/read")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": slash_id}

    # Verify the read mark stuck.
    assert (await client.get("/notifications/unread-count")).json() == {"count": 0}


@pytest.mark.asyncio
async def test_mark_read_handles_slash_in_id_under_api_prefix(
    client: AsyncClient, store_with_fakeredis
) -> None:
    slash_id = "trade:sell:ETH/USD:trace-abc"
    await store_with_fakeredis.push_notification({"id": slash_id, "title": "x"})
    r = await client.post(f"/api/notifications/{slash_id}/read")
    assert r.status_code == 200
    assert r.json()["id"] == slash_id
