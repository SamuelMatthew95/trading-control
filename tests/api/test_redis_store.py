"""Regression tests for the Redis-backed REST persistence layer.

Covers the contract the dashboard relies on:
- LPUSH + LTRIM never lets a list exceed its declared cap, even under
  concurrent writers.
- Stats endpoint counts only the trailing hour.
- LLM metrics accumulate correctly across many record_* calls.
- mark_read + unread_count interact correctly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from api.constants import (
    REDIS_DECISIONS_MAX,
    REDIS_KEY_DECISIONS_RECENT,
    REDIS_KEY_NOTIFICATIONS_RECENT,
    REDIS_NOTIFICATIONS_MAX,
    FieldName,
)
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store


@pytest.fixture
def store_singleton_reset():
    """Restore the global RedisStore singleton between tests."""
    previous = get_redis_store()
    yield
    set_redis_store(previous)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_notification_assigns_defaults(fake_redis) -> None:
    store = RedisStore(fake_redis)
    entry = await store.push_notification({"title": "hello"})
    assert "id" in entry
    assert entry["severity"] == "info"
    assert entry["read"] is False
    assert FieldName.TIMESTAMP in entry


@pytest.mark.asyncio
async def test_notifications_list_cap_is_enforced_under_burst(fake_redis) -> None:
    store = RedisStore(fake_redis)
    over_cap = REDIS_NOTIFICATIONS_MAX + 25
    # Fire pushes concurrently to exercise the pipeline path.
    await asyncio.gather(*(store.push_notification({"title": f"n-{i}"}) for i in range(over_cap)))
    length = await fake_redis.llen(REDIS_KEY_NOTIFICATIONS_RECENT)
    assert length == REDIS_NOTIFICATIONS_MAX

    # list_notifications honours the explicit ``limit`` ceiling.
    items = await store.list_notifications(limit=10)
    assert len(items) == 10
    # Items are ordered newest-first (LPUSH semantics).
    assert items[0]["title"] == f"n-{over_cap - 1}"


@pytest.mark.asyncio
async def test_mark_read_flows_into_list_and_unread_count(fake_redis) -> None:
    store = RedisStore(fake_redis)
    a = await store.push_notification({"title": "a"})
    b = await store.push_notification({"title": "b"})
    c = await store.push_notification({"title": "c"})

    assert await store.unread_count() == 3
    assert await store.mark_read(a["id"]) is True
    assert await store.unread_count() == 2

    items = await store.list_notifications(limit=10)
    by_id = {item["id"]: item for item in items}
    assert by_id[a["id"]]["read"] is True
    assert by_id[b["id"]]["read"] is False
    assert by_id[c["id"]]["read"] is False


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decisions_list_cap_is_enforced(fake_redis) -> None:
    store = RedisStore(fake_redis)
    over_cap = REDIS_DECISIONS_MAX + 5
    for i in range(over_cap):
        await store.push_decision({FieldName.ACTION: "hold", FieldName.SYMBOL: f"S-{i}"})
    length = await fake_redis.llen(REDIS_KEY_DECISIONS_RECENT)
    assert length == REDIS_DECISIONS_MAX


@pytest.mark.asyncio
async def test_list_decisions_filter_by_action(fake_redis) -> None:
    store = RedisStore(fake_redis)
    for action in ("buy", "sell", "hold", "buy", "hold"):
        await store.push_decision({FieldName.ACTION: action, FieldName.SYMBOL: "BTC/USD"})
    buys = await store.list_decisions(limit=50, action="buy")
    assert len(buys) == 2
    assert {d[FieldName.ACTION] for d in buys} == {"buy"}

    # limit is honoured after filtering.
    one_buy = await store.list_decisions(limit=1, action="buy")
    assert len(one_buy) == 1


@pytest.mark.asyncio
async def test_decision_stats_only_counts_last_hour(fake_redis) -> None:
    store = RedisStore(fake_redis)
    now = datetime.now(timezone.utc)
    stale_iso = (now - timedelta(hours=3)).isoformat()
    # Pre-seed an "old" entry directly so we control its timestamp.
    await fake_redis.lpush(
        REDIS_KEY_DECISIONS_RECENT,
        json.dumps(
            {
                "id": "stale",
                FieldName.TIMESTAMP: stale_iso,
                FieldName.ACTION: "buy",
                FieldName.SYMBOL: "BTC/USD",
            }
        ),
    )
    # Recent decisions
    await store.push_decision({FieldName.ACTION: "buy", FieldName.SYMBOL: "BTC/USD"})
    await store.push_decision({FieldName.ACTION: "sell", FieldName.SYMBOL: "ETH/USD"})
    await store.push_decision({FieldName.ACTION: "hold", FieldName.SYMBOL: "BTC/USD"})

    stats = await store.decision_stats()
    assert stats["total"] == 4
    assert stats["last_hour"] == {"buys": 1, "sells": 1, "holds": 1}
    assert stats["last_decision"] is not None


@pytest.mark.asyncio
async def test_decision_stats_empty_when_redis_empty(fake_redis) -> None:
    store = RedisStore(fake_redis)
    stats = await store.decision_stats()
    assert stats == {
        "total": 0,
        "last_hour": {"buys": 0, "sells": 0, "holds": 0},
        "last_decision": None,
    }


# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_llm_call_increments_counters(fake_redis) -> None:
    store = RedisStore(fake_redis)
    await store.record_llm_call(outcome="success", latency_ms=120.0)
    await store.record_llm_call(outcome="success", latency_ms=80.0)
    await store.record_llm_call(outcome="rate_limit")
    await store.record_llm_call(outcome="timeout")
    await store.record_llm_call(outcome="error")

    metrics = await store.get_llm_metrics()
    assert metrics["total_calls"] == 5
    assert metrics["successes"] == 2
    assert metrics["rate_limits"] == 1
    assert metrics["timeouts"] == 1
    assert metrics["errors"] == 1
    assert metrics["last_latency_ms"] == 80
    assert metrics["last_success_at"]


@pytest.mark.asyncio
async def test_get_llm_metrics_empty_when_no_calls(fake_redis) -> None:
    store = RedisStore(fake_redis)
    assert await store.get_llm_metrics() == {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_and_get_singleton(fake_redis, store_singleton_reset) -> None:
    store = RedisStore(fake_redis)
    set_redis_store(store)
    assert get_redis_store() is store
    set_redis_store(None)
    assert get_redis_store() is None
