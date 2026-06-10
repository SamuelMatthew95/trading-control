"""Tests for ChallengerSpawner guardrails — strategy dedup + concurrency cap.

Regression: the auto-applied promotion loop (promotion → spawn candidate of
the winning strategy → candidate beats baseline → promotes again) appended a
near-identical challenger to the live fleet on every cycle, without bound —
the dashboard showed 15+ clones of the same strategy at 0 fills each.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import MAX_CONCURRENT_CHALLENGERS, FieldName
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.pipeline_agents import ChallengerAgent
from api.services.challenger_spawner import ChallengerSpawner

pytestmark = pytest.mark.asyncio


@pytest.fixture
def spawner(monkeypatch):
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()

    # Don't start real consume loops in tests — just mark the agent running,
    # which is the liveness signal the spawner's dedup/cap checks read.
    async def _fake_start(self) -> None:
        self._running = True

    monkeypatch.setattr(ChallengerAgent, "start", _fake_start)
    return ChallengerSpawner(bus, dlq, agents=[])


async def test_spawn_dedupes_per_running_strategy(spawner):
    first = await spawner.spawn({FieldName.STRATEGY: "mean_reversion"})
    assert first[FieldName.STATUS] == "spawned"

    second = await spawner.spawn({FieldName.STRATEGY: "mean_reversion"})
    assert second[FieldName.STATUS] == "already_running"
    assert second[FieldName.CHALLENGER_ID] == first[FieldName.CHALLENGER_ID]
    # The fleet did NOT grow — one running challenger per strategy.
    assert len(spawner.agents) == 1


async def test_spawn_refuses_beyond_concurrency_cap(spawner):
    for i in range(MAX_CONCURRENT_CHALLENGERS):
        result = await spawner.spawn({FieldName.STRATEGY: f"strategy_{i}"})
        assert result[FieldName.STATUS] == "spawned"

    overflow = await spawner.spawn({FieldName.STRATEGY: "one_too_many"})
    assert overflow[FieldName.STATUS] == "capacity"
    assert len(spawner.agents) == MAX_CONCURRENT_CHALLENGERS


async def test_retired_challenger_frees_its_strategy_slot(spawner):
    first = await spawner.spawn({FieldName.STRATEGY: "mean_reversion"})
    assert first[FieldName.STATUS] == "spawned"
    spawner.agents[0]._running = False  # retired (max fills reached / stopped)

    replacement = await spawner.spawn({FieldName.STRATEGY: "mean_reversion"})
    assert replacement[FieldName.STATUS] == "spawned"
    assert replacement[FieldName.CHALLENGER_ID] != first[FieldName.CHALLENGER_ID]
