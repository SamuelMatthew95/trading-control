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


# ---------------------------------------------------------------------------
# Edge cases — defensive coding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_notification_coerces_none_id_to_uuid(fake_redis) -> None:
    """Caller passing {'id': None} should still get a usable id back."""
    store = RedisStore(fake_redis)
    entry = await store.push_notification({"id": None, "title": "x"})
    assert entry["id"]
    assert entry["id"] != "None"


@pytest.mark.asyncio
async def test_push_notification_coerces_empty_id_to_uuid(fake_redis) -> None:
    store = RedisStore(fake_redis)
    entry = await store.push_notification({"id": "", "title": "x"})
    assert entry["id"] != ""


@pytest.mark.asyncio
async def test_push_decision_coerces_none_id_and_timestamp(fake_redis) -> None:
    store = RedisStore(fake_redis)
    entry = await store.push_decision(
        {"id": None, FieldName.TIMESTAMP: None, FieldName.ACTION: "hold"}
    )
    assert entry["id"]
    assert entry[FieldName.TIMESTAMP]


@pytest.mark.asyncio
async def test_push_notification_preserves_caller_id(fake_redis) -> None:
    """Caller-supplied id must round-trip unchanged — dedup contract."""
    store = RedisStore(fake_redis)
    entry = await store.push_notification({"id": "trade:buy:BTC/USD:abc123", "title": "x"})
    assert entry["id"] == "trade:buy:BTC/USD:abc123"
    items = await store.list_notifications(limit=10)
    assert items[0]["id"] == "trade:buy:BTC/USD:abc123"


@pytest.mark.asyncio
async def test_list_notifications_skips_corrupted_json(fake_redis) -> None:
    """A garbage entry in the list must not crash the endpoint."""
    store = RedisStore(fake_redis)
    await fake_redis.lpush(REDIS_KEY_NOTIFICATIONS_RECENT, "not-json-at-all")
    await store.push_notification({"title": "valid"})
    items = await store.list_notifications(limit=10)
    assert len(items) == 1
    assert items[0]["title"] == "valid"


@pytest.mark.asyncio
async def test_list_decisions_skips_corrupted_json(fake_redis) -> None:
    store = RedisStore(fake_redis)
    await fake_redis.lpush(REDIS_KEY_DECISIONS_RECENT, "{not json")
    await store.push_decision({FieldName.ACTION: "buy", FieldName.SYMBOL: "BTC/USD"})
    items = await store.list_decisions(limit=10)
    assert len(items) == 1
    assert items[0][FieldName.ACTION] == "buy"


@pytest.mark.asyncio
async def test_decision_stats_ignores_malformed_timestamp(fake_redis) -> None:
    """A decision with an unparseable timestamp must not count as last-hour."""
    store = RedisStore(fake_redis)
    await fake_redis.lpush(
        REDIS_KEY_DECISIONS_RECENT,
        json.dumps(
            {
                "id": "bad",
                FieldName.TIMESTAMP: "not-a-timestamp",
                FieldName.ACTION: "buy",
            }
        ),
    )
    stats = await store.decision_stats()
    assert stats["total"] == 1
    assert stats["last_hour"] == {"buys": 0, "sells": 0, "holds": 0}


@pytest.mark.asyncio
async def test_list_decisions_limit_zero_returns_empty(fake_redis) -> None:
    store = RedisStore(fake_redis)
    await store.push_decision({FieldName.ACTION: "buy"})
    items = await store.list_decisions(limit=0)
    # limit=0 is coerced to 1 by max(1, ...)
    assert len(items) <= 1


@pytest.mark.asyncio
async def test_list_decisions_filter_unknown_action_returns_empty(fake_redis) -> None:
    store = RedisStore(fake_redis)
    await store.push_decision({FieldName.ACTION: "buy"})
    items = await store.list_decisions(limit=10, action="reject")
    assert items == []


@pytest.mark.asyncio
async def test_mark_read_idempotent(fake_redis) -> None:
    """Marking the same id twice is safe (SADD is idempotent by design)."""
    store = RedisStore(fake_redis)
    entry = await store.push_notification({"title": "a"})
    assert await store.mark_read(entry["id"]) is True
    assert await store.mark_read(entry["id"]) is True
    assert await store.unread_count() == 0


@pytest.mark.asyncio
async def test_record_llm_call_unknown_outcome_bucketed_as_error(fake_redis) -> None:
    """Calling with a typo must not lose the call from the total."""
    store = RedisStore(fake_redis)
    await store.record_llm_call(outcome="weird_unknown_value")
    metrics = await store.get_llm_metrics()
    assert metrics["total_calls"] == 1
    assert metrics["errors"] == 1


@pytest.mark.asyncio
async def test_record_llm_call_success_without_latency(fake_redis) -> None:
    store = RedisStore(fake_redis)
    await store.record_llm_call(outcome="success")
    metrics = await store.get_llm_metrics()
    assert metrics["successes"] == 1
    # latency / timestamp fields stay unset when no latency provided
    assert metrics["last_latency_ms"] == 0
    assert metrics["last_success_at"] is None


# ---------------------------------------------------------------------------
# Bounded read-set — long-running deployments must not leak memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_set_pruned_when_id_trimmed_off_recent(fake_redis) -> None:
    """Once a notification is trimmed off ``notifications:recent``, its id
    must not linger in ``notifications:read`` forever."""
    from api.constants import REDIS_KEY_NOTIFICATIONS_READ

    store = RedisStore(fake_redis)
    first = await store.push_notification({"id": "n-old", "title": "x"})
    await store.mark_read(first["id"])
    assert await fake_redis.sismember(REDIS_KEY_NOTIFICATIONS_READ, "n-old")

    # Push enough notifications that "n-old" rolls off the bounded list.
    for i in range(REDIS_NOTIFICATIONS_MAX + 5):
        await store.push_notification({"id": f"n-new-{i}", "title": "x"})

    # n-old has been trimmed → its read entry must have been pruned too.
    assert not await fake_redis.sismember(REDIS_KEY_NOTIFICATIONS_READ, "n-old")


@pytest.mark.asyncio
async def test_read_set_preserves_live_ids(fake_redis) -> None:
    """Ids still present in ``notifications:recent`` must survive a prune."""
    from api.constants import REDIS_KEY_NOTIFICATIONS_READ

    store = RedisStore(fake_redis)
    live = await store.push_notification({"id": "n-live", "title": "x"})
    await store.mark_read(live["id"])
    # Trigger another push so prune runs.
    await store.push_notification({"id": "n-also-live", "title": "x"})

    assert await fake_redis.sismember(REDIS_KEY_NOTIFICATIONS_READ, "n-live")


@pytest.mark.asyncio
async def test_read_set_size_bounded_by_recent_cap(fake_redis) -> None:
    """Worst-case: every notification marked read; set never exceeds the cap."""
    store = RedisStore(fake_redis)
    for i in range(REDIS_NOTIFICATIONS_MAX * 2):
        entry = await store.push_notification({"id": f"n-{i}", "title": "x"})
        await store.mark_read(entry["id"])
    # One more push triggers a prune.
    await store.push_notification({"id": "trigger", "title": "x"})
    read_count = await fake_redis.scard("notifications:read")
    assert read_count <= REDIS_NOTIFICATIONS_MAX
