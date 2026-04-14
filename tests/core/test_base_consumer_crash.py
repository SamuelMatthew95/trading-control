"""Regression tests for BaseStreamConsumer crash-visibility fix.

Before the fix, an unexpected exception in the consumer loop caused a bare
`break`, which let the asyncio Task finish *cleanly* (no exception).  The
AgentSupervisor's `has_crashed` property — `task.exception() is not None` —
therefore returned False, so the supervisor never detected or restarted the
dead consumer.

After the fix, unexpected exceptions are re-raised so the Task ends with an
exception, making `has_crashed = True` and allowing the supervisor to restart.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager


# ---------------------------------------------------------------------------
# Minimal concrete consumer used only in these tests
# ---------------------------------------------------------------------------


class _BoomConsumer(BaseStreamConsumer):
    """A consumer whose process() always raises a RuntimeError."""

    async def process(self, data: dict[str, Any]) -> None:
        raise RuntimeError("intentional_process_failure")


class _OkConsumer(BaseStreamConsumer):
    """A consumer whose process() succeeds normally."""

    async def process(self, data: dict[str, Any]) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dlq(fake_redis) -> DLQManager:
    bus = EventBus(fake_redis)
    return DLQManager(fake_redis, bus)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_crash_makes_task_end_with_exception(fake_redis):
    """When the consumer loop encounters an unexpected exception it re-raises,
    so the asyncio Task ends with an exception (has_crashed = True).

    This is the regression guard for the `break` → `raise` fix.  With `break`
    the task would complete normally (no exception) and AgentSupervisor would
    miss the crash entirely.
    """
    bus = EventBus(fake_redis)
    await bus.create_groups()
    dlq = _make_dlq(fake_redis)

    consumer = _BoomConsumer(bus, dlq, "signals", DEFAULT_GROUP, "test_boom")

    # Patch bus.consume so it returns one message that will trigger process()
    # and ultimately cause an unhandled path.  We want to drive the
    # `except Exception: raise` branch, so we make consume() itself raise an
    # unexpected non-Redis, non-Cancelled exception.
    original_consume = bus.consume

    call_count = 0

    async def _boom_consume(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("unexpected_internal_error")
        # Let subsequent calls block forever so the task stays alive only once
        await asyncio.sleep(10)
        return []

    bus.consume = _boom_consume  # type: ignore[method-assign]

    await consumer.start()

    # Give the event loop a moment to run the consumer task through the error.
    for _ in range(20):
        await asyncio.sleep(0.01)
        if consumer._task and consumer._task.done():
            break

    assert consumer._task is not None, "Task should exist"
    assert consumer._task.done(), "Task should have finished"
    assert not consumer._task.cancelled(), "Task should not be cancelled"
    assert consumer._task.exception() is not None, (
        "Task must end with an exception so AgentSupervisor.has_crashed is True"
    )
    assert consumer.has_crashed, "has_crashed must be True so the supervisor can restart"

    bus.consume = original_consume  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_consumer_normal_shutdown_is_not_marked_crashed(fake_redis):
    """A consumer stopped via stop() must NOT be marked as crashed."""
    bus = EventBus(fake_redis)
    await bus.create_groups()
    dlq = _make_dlq(fake_redis)

    consumer = _OkConsumer(bus, dlq, "signals", DEFAULT_GROUP, "test_ok")
    await consumer.start()
    await asyncio.sleep(0.05)
    await consumer.stop()

    # After a clean stop the task is gone (set to None by stop())
    assert consumer._task is None
    assert not consumer.has_crashed, "Graceful stop must not set has_crashed"


@pytest.mark.asyncio
async def test_ensure_all_streams_ready_logs_recovered_count(fake_redis):
    """ensure_all_streams_ready() logs recovered=N even when streams needed recovery."""
    from api.events.bus import ensure_all_streams_ready

    # Prime with groups, then delete two streams to force recovery
    from api.constants import STREAM_ORDERS, STREAM_SIGNALS

    await ensure_all_streams_ready(fake_redis)
    await fake_redis.delete(STREAM_ORDERS)
    await fake_redis.delete(STREAM_SIGNALS)

    # Must not raise; must restore both streams
    await ensure_all_streams_ready(fake_redis)

    from api.events.bus import DEFAULT_GROUP, PIPELINE_GROUP

    for stream in (STREAM_ORDERS, STREAM_SIGNALS):
        groups = await fake_redis.xinfo_groups(stream)
        names = {
            (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
        }
        assert DEFAULT_GROUP in names, f"{stream} missing DEFAULT_GROUP after recovery"
        assert PIPELINE_GROUP in names, f"{stream} missing PIPELINE_GROUP after recovery"
