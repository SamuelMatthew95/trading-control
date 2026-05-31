"""Regression tests for BaseStreamConsumer crash-visibility fix and
MultiStreamAgent supervisor-compatibility fix.

Before the first fix, an unexpected exception in the consumer loop caused a
bare `break`, which let the asyncio Task finish *cleanly* (no exception).
The AgentSupervisor's `has_crashed` property — `task.exception() is not None`
— therefore returned False, so the supervisor never detected or restarted the
dead consumer.

After the first fix, unexpected exceptions are re-raised so the Task ends with
an exception, making `has_crashed = True` and allowing the supervisor to restart.

Before the second fix, MultiStreamAgent had no `has_crashed` or `name`
properties. The AgentSupervisor iterates all agents in its list; accessing
`agent.has_crashed` on a MultiStreamAgent raised AttributeError, which caused
the entire health-check iteration to abort — leaving GradeAgent, ICUpdater,
ReflectionAgent, StrategyProposer, and NotificationAgent permanently unmonitored.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.services.agents.base import MultiStreamAgent

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
async def test_consumer_start_writes_instance_and_lifecycle(monkeypatch, fake_redis):
    bus = EventBus(fake_redis)
    await bus.create_groups()
    dlq = _make_dlq(fake_redis)
    consumer = _OkConsumer(bus, dlq, "signals", DEFAULT_GROUP, "test-ok")

    register = AsyncMock(return_value="instance-123")
    lifecycle = AsyncMock()
    retire = AsyncMock()
    monkeypatch.setattr("api.services.agents.db_helpers.register_agent_instance", register)
    monkeypatch.setattr("api.services.agents.db_helpers.write_agent_lifecycle_event", lifecycle)
    monkeypatch.setattr("api.services.agents.db_helpers.retire_agent_instance", retire)

    await consumer.start()
    await consumer.stop()

    register.assert_awaited_once()
    assert any(c.kwargs.get("lifecycle_phase") == "started" for c in lifecycle.await_args_list)


@pytest.mark.asyncio
async def test_ensure_all_streams_ready_logs_recovered_count(fake_redis):
    """ensure_all_streams_ready() logs recovered=N even when streams needed recovery."""
    # Prime with groups, then delete two streams to force recovery
    from api.constants import STREAM_ORDERS, STREAM_SIGNALS
    from api.events.bus import ensure_all_streams_ready

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


# ---------------------------------------------------------------------------
# MultiStreamAgent supervisor-compatibility tests
# ---------------------------------------------------------------------------


class _NullMultiAgent(MultiStreamAgent):
    """Minimal MultiStreamAgent that does nothing — used only in these tests."""

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        pass


def test_multi_stream_agent_has_crashed_property_before_start():
    """MultiStreamAgent.has_crashed must exist and return False before start().

    Regression guard: before the fix, accessing has_crashed raised AttributeError,
    causing AgentSupervisor._check_health() to abort and leave GradeAgent+
    permanently unmonitored.
    """
    from unittest.mock import MagicMock

    bus = MagicMock()
    dlq = MagicMock()
    agent = _NullMultiAgent(bus, dlq, streams=["signals"], consumer="test-null-agent")

    # Must not raise AttributeError
    assert hasattr(agent, "has_crashed"), "MultiStreamAgent must expose has_crashed"
    assert not agent.has_crashed, "has_crashed must be False before task is started"


def test_multi_stream_agent_name_property():
    """MultiStreamAgent.name must return the consumer string."""
    from unittest.mock import MagicMock

    bus = MagicMock()
    dlq = MagicMock()
    agent = _NullMultiAgent(bus, dlq, streams=["signals"], consumer="grade-agent")

    assert agent.name == "grade-agent"


def test_agent_supervisor_iterates_mixed_agent_list():
    """AgentSupervisor._check_health() must not raise when the agents list contains
    both BaseStreamConsumer and MultiStreamAgent instances.

    Before the fix, the first MultiStreamAgent (GradeAgent, 4th in the list)
    caused AttributeError on .has_crashed, aborting the entire health check.
    """
    import asyncio
    from unittest.mock import MagicMock

    from api.services.agent_supervisor import AgentSupervisor

    # Build fake agents: first two look like BaseStreamConsumer (have the property),
    # third is our null MultiStreamAgent.
    fake_bsc_1 = MagicMock()
    fake_bsc_1.has_crashed = False
    fake_bsc_2 = MagicMock()
    fake_bsc_2.has_crashed = False

    bus = MagicMock()
    dlq = MagicMock()
    multi_agent = _NullMultiAgent(bus, dlq, streams=["signals"], consumer="test-multi")

    bus_mock = MagicMock()
    supervisor = AgentSupervisor(bus_mock, [fake_bsc_1, fake_bsc_2, multi_agent])

    # _check_health() must not raise
    async def _run():
        await supervisor._check_health()

    asyncio.run(_run())


def test_agent_supervisor_restart_is_rate_limited():
    """Supervisor should suppress restarts after max attempts within time window."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from api.constants import SUPERVISOR_MAX_RESTARTS_PER_WINDOW
    from api.services.agent_supervisor import AgentSupervisor

    agent = MagicMock()
    agent.has_crashed = True
    agent.name = "reflection-agent"
    agent._task = MagicMock()
    agent._task.exception.return_value = RuntimeError("boom")
    agent.start = AsyncMock()

    bus_mock = MagicMock()
    bus_mock.publish = AsyncMock()
    supervisor = AgentSupervisor(bus_mock, [agent])

    async def _run_checks() -> None:
        for _ in range(SUPERVISOR_MAX_RESTARTS_PER_WINDOW + 1):
            await supervisor._check_health()

    asyncio.run(_run_checks())

    assert agent.start.await_count == SUPERVISOR_MAX_RESTARTS_PER_WINDOW


# ---------------------------------------------------------------------------
# RiskGuardian / AgentSupervisor uniform-interface tests
# ---------------------------------------------------------------------------
#
# RiskGuardian and AgentSupervisor are background-task agents (not stream
# consumers). They must expose the same `name` / `has_crashed` introspection the
# supervisor reads, so RiskGuardian can be monitored uniformly alongside the
# stream agents — the stop-loss / daily-loss monitor must be restarted if its
# task ever dies. Before this fix RiskGuardian was started but never supervised.


def test_risk_guardian_exposes_supervisor_interface():
    """RiskGuardian must expose name + has_crashed so AgentSupervisor can iterate
    it without AttributeError. has_crashed is False before the task starts."""
    from unittest.mock import MagicMock

    from api.services.agents.risk_guardian import RiskGuardian

    rg = RiskGuardian(MagicMock(), MagicMock())

    assert rg.name == "risk_guardian"
    assert hasattr(rg, "has_crashed")
    assert not rg.has_crashed, "has_crashed must be False before the task is started"


@pytest.mark.asyncio
async def test_risk_guardian_has_crashed_true_after_task_dies():
    """has_crashed flips True when the background task finishes with an exception,
    so AgentSupervisor can detect and restart a dead RiskGuardian."""
    from unittest.mock import MagicMock

    from api.services.agents.risk_guardian import RiskGuardian

    rg = RiskGuardian(MagicMock(), MagicMock())

    async def _boom() -> None:
        raise RuntimeError("risk_guardian_died")

    rg._task = asyncio.ensure_future(_boom())
    for _ in range(20):
        await asyncio.sleep(0.01)
        if rg._task.done():
            break

    assert rg._task.done() and not rg._task.cancelled()
    assert rg.has_crashed, "supervisor relies on has_crashed to restart a dead RiskGuardian"


def test_agent_supervisor_exposes_uniform_interface():
    """AgentSupervisor exposes the same name + has_crashed interface as the agents
    it supervises (uniformity); has_crashed is False before its task starts."""
    from unittest.mock import MagicMock

    from api.services.agent_supervisor import AgentSupervisor

    supervisor = AgentSupervisor(MagicMock(), [])

    assert supervisor.name == "agent_supervisor"
    assert not supervisor.has_crashed


def test_agent_supervisor_iterates_list_including_risk_guardian():
    """_check_health() must not raise when the supervised list contains a real
    RiskGuardian — the regression guard for 'RiskGuardian not monitored'."""
    from unittest.mock import MagicMock

    from api.services.agent_supervisor import AgentSupervisor
    from api.services.agents.risk_guardian import RiskGuardian

    rg = RiskGuardian(MagicMock(), MagicMock())
    supervisor = AgentSupervisor(MagicMock(), [rg])

    asyncio.run(supervisor._check_health())  # must not raise


def test_startup_wires_risk_guardian_into_supervisor():
    """startup must pass RiskGuardian into AgentSupervisor so it is monitored.
    Source-level guard against reverting to AgentSupervisor(event_bus, agents)."""
    import re
    from pathlib import Path

    startup_src = (Path(__file__).resolve().parents[2] / "api" / "startup.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"AgentSupervisor\((.*?)\)", startup_src, re.DOTALL)
    assert match is not None, "AgentSupervisor construction not found in startup.py"
    assert "risk_guardian" in match.group(1), (
        "AgentSupervisor must be constructed with risk_guardian in its supervised list"
    )
