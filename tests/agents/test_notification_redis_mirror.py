"""Tests for the NotificationAgent → RedisStore mirror.

The mirror is what makes GET /api/notifications return real data after a
trade fill, so verify:

- A normal notification is written to RedisStore with id + severity set.
- Missing RedisStore singleton is silently tolerated (best-effort contract).
- A RedisStore push failure does NOT propagate out of the mirror.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.constants import FieldName
from api.services.agents.pipeline_agents import NotificationAgent
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store


@pytest.fixture
def fresh_singleton():
    """Restore whatever store was installed before the test."""
    previous = get_redis_store()
    yield
    set_redis_store(previous)


@pytest.mark.asyncio
async def test_mirror_writes_notification_to_redis(fake_redis, fresh_singleton) -> None:
    set_redis_store(RedisStore(fake_redis))

    notification = {
        FieldName.NOTIFICATION_ID: "trade:buy:BTC/USD:1",
        "title": "BUY filled: BTC/USD",
        "message": "BUY BTC/USD filled",
    }
    await NotificationAgent._mirror_notification_to_redis_store(
        notification, severity="INFO", observed_msg_id="msg-1"
    )

    items = await get_redis_store().list_notifications(limit=10)
    assert len(items) == 1
    assert items[0]["id"] == "trade:buy:BTC/USD:1"
    assert items[0]["severity"] == "INFO"
    assert items[0]["title"] == "BUY filled: BTC/USD"


@pytest.mark.asyncio
async def test_mirror_falls_back_to_observed_msg_id(fake_redis, fresh_singleton) -> None:
    """When notification_id is absent, mirror should use the observed Redis stream id."""
    set_redis_store(RedisStore(fake_redis))
    await NotificationAgent._mirror_notification_to_redis_store(
        {"title": "x"}, severity="INFO", observed_msg_id="stream-id-7"
    )
    items = await get_redis_store().list_notifications(limit=10)
    assert items[0]["id"] == "stream-id-7"


@pytest.mark.asyncio
async def test_mirror_no_op_when_singleton_missing(fresh_singleton) -> None:
    """Must not raise when no RedisStore is installed."""
    set_redis_store(None)
    # Should silently return without touching anything.
    await NotificationAgent._mirror_notification_to_redis_store(
        {"title": "x"}, severity="INFO", observed_msg_id="msg-1"
    )


@pytest.mark.asyncio
async def test_mirror_swallows_push_failure(fresh_singleton) -> None:
    """A RedisStore push exception must not propagate out of the mirror."""

    failing_store = RedisStore.__new__(RedisStore)
    failing_store.push_notification = AsyncMock(side_effect=RuntimeError("redis down"))
    set_redis_store(failing_store)

    # No exception should be raised — best-effort contract.
    await NotificationAgent._mirror_notification_to_redis_store(
        {"title": "x"}, severity="INFO", observed_msg_id="msg-1"
    )
    failing_store.push_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_mirror_preserves_caller_severity_when_notification_omits(
    fake_redis, fresh_singleton
) -> None:
    set_redis_store(RedisStore(fake_redis))
    await NotificationAgent._mirror_notification_to_redis_store(
        {"title": "x"}, severity="URGENT", observed_msg_id="m"
    )
    items = await get_redis_store().list_notifications(limit=10)
    assert items[0]["severity"] == "URGENT"
