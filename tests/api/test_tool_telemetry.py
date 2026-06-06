"""Durable tool-telemetry persistence — load on startup, flush periodically.

Verifies the bridge between the in-process ToolRegistry and Redis so real tool
usage (call_count / alpha / latency) survives a process restart instead of
resetting to seeded priors.
"""

from __future__ import annotations

import pytest

from api.constants import ToolPhase
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store
from api.services.tool_registry import (
    ToolMetadata,
    ToolRegistry,
    get_tool_registry,
    set_tool_registry,
)
from api.services.tool_telemetry import flush_tool_registry, hydrate_tool_registry


@pytest.fixture
def restore_singletons():
    prev_store = get_redis_store()
    prev_registry = get_tool_registry()
    yield
    set_redis_store(prev_store)
    set_tool_registry(prev_registry)


@pytest.mark.asyncio
async def test_flush_then_hydrate_restores_usage(fake_redis, restore_singletons):
    set_redis_store(RedisStore(fake_redis))

    # A registry that has exercised a tool.
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY))
    reg.record_call("t", latency_ms=12.0, success=True, realized_pnl=3.0)
    set_tool_registry(reg)
    await flush_tool_registry()

    # Simulate a restart: a fresh registry with the same catalog at priors.
    fresh = ToolRegistry()
    fresh.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY))
    set_tool_registry(fresh)
    assert fresh.get("t").call_count == 0

    restored = await hydrate_tool_registry()
    assert restored == 1
    tool = get_tool_registry().get("t")
    assert tool.call_count == 1
    assert tool.alpha_score == 3.0


@pytest.mark.asyncio
async def test_hydrate_is_noop_without_store(restore_singletons):
    set_redis_store(None)
    assert await hydrate_tool_registry() == 0


@pytest.mark.asyncio
async def test_flush_is_noop_without_store(restore_singletons):
    set_redis_store(None)
    # Should not raise.
    await flush_tool_registry()
