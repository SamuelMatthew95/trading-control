"""Tests for the llm_metrics → RedisStore fire-and-forget bridge.

``LLMMetricsCollector.record_*`` is synchronous; the Redis write happens
in a fire-and-forget task. We have to:

- Verify the task actually runs and updates Redis (await an asyncio yield).
- Verify the task reference is held until completion so it isn't GC'd.
- Verify no exception leaks when no RedisStore is installed.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services import llm_metrics as llm_metrics_module
from api.services.llm_metrics import LLMMetricsCollector
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store


@pytest.fixture
def fresh_singleton():
    previous = get_redis_store()
    yield
    set_redis_store(previous)


@pytest.mark.asyncio
async def test_record_success_bridges_to_redis(fake_redis, fresh_singleton) -> None:
    set_redis_store(RedisStore(fake_redis))

    collector = LLMMetricsCollector()
    collector.record_success(latency_ms=99.0)
    # Yield control so the scheduled fire-and-forget task can complete.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    metrics = await get_redis_store().get_llm_metrics()
    assert metrics["total_calls"] == 1
    assert metrics["successes"] == 1
    assert metrics["last_latency_ms"] == 99


@pytest.mark.asyncio
async def test_record_rate_limit_bridges_to_redis(fake_redis, fresh_singleton) -> None:
    set_redis_store(RedisStore(fake_redis))

    collector = LLMMetricsCollector()
    collector.record_rate_limit()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    metrics = await get_redis_store().get_llm_metrics()
    assert metrics["rate_limits"] == 1
    assert metrics["total_calls"] == 1


@pytest.mark.asyncio
async def test_record_timeout_bridges_to_redis(fake_redis, fresh_singleton) -> None:
    set_redis_store(RedisStore(fake_redis))

    collector = LLMMetricsCollector()
    collector.record_timeout()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    metrics = await get_redis_store().get_llm_metrics()
    assert metrics["timeouts"] == 1


@pytest.mark.asyncio
async def test_record_error_bridges_to_redis(fake_redis, fresh_singleton) -> None:
    set_redis_store(RedisStore(fake_redis))

    collector = LLMMetricsCollector()
    collector.record_error(message="boom", kind="provider_error")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    metrics = await get_redis_store().get_llm_metrics()
    assert metrics["errors"] == 1


@pytest.mark.asyncio
async def test_record_without_redis_store_is_safe(fresh_singleton) -> None:
    """No RedisStore installed → record_* must not raise."""
    set_redis_store(None)
    collector = LLMMetricsCollector()
    collector.record_success(latency_ms=10.0)
    collector.record_rate_limit()
    collector.record_timeout()
    collector.record_error(message="x")
    await asyncio.sleep(0)
    # In-process ring buffer still tracks the call.
    snap = collector.snapshot()
    assert snap["total_calls_lifetime"] == 4


@pytest.mark.asyncio
async def test_pending_task_set_drains_after_completion(fake_redis, fresh_singleton) -> None:
    """Tasks we schedule here must complete and leave the set unchanged."""
    set_redis_store(RedisStore(fake_redis))

    # Snapshot baseline so we don't trip on leftover tasks from other tests
    # that may still be scheduled on this event loop. We only care that the
    # tasks WE create complete.
    baseline = len(llm_metrics_module._pending_redis_tasks)

    collector = LLMMetricsCollector()
    collector.record_success(latency_ms=5.0)
    collector.record_success(latency_ms=5.0)
    collector.record_rate_limit()
    # Allow the loop to run all scheduled tasks.
    for _ in range(5):
        await asyncio.sleep(0)
    # The set should drain back to what it was before we added our tasks.
    assert len(llm_metrics_module._pending_redis_tasks) <= baseline


def test_fire_and_forget_outside_event_loop_is_silent() -> None:
    """Calling record_* off-loop must close the coroutine cleanly."""
    # We're in a sync test, so there is no running loop. The collector should
    # gracefully no-op the Redis bridge rather than raising.
    collector = LLMMetricsCollector()
    collector.record_success(latency_ms=1.0)
    collector.record_rate_limit()
    # If we got here, the bridge silently swallowed the missing loop.
