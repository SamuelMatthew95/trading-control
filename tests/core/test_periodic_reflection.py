"""Periodic reflection safety-net loop (api/startup._periodic_reflection_loop).

Keeps the learning loop producing proposals when the per-fill trigger is quiet:
reflects once over seeded history after startup, then only when new fills have
arrived since the last reflection.
"""

from __future__ import annotations

import asyncio

import pytest

from api import startup
from api.config import settings


class _FakeReflectionAgent:
    def __init__(self, fills: int) -> None:
        self._n = fills
        self.reflect_calls = 0

    def buffered_fill_count(self) -> int:
        return self._n

    def fills_seen(self) -> int:
        return self._n

    async def trigger_reflection(self) -> dict:
        self.reflect_calls += 1
        return {}


@pytest.mark.asyncio
async def test_periodic_loop_reflects_once_then_gates_on_new_fills(monkeypatch):
    monkeypatch.setattr(settings, "REFLECTION_PERIODIC_SECONDS", 1)
    monkeypatch.setattr(settings, "REFLECT_MIN_FILLS", 1)
    agent = _FakeReflectionAgent(fills=3)

    sleeps = {"n": 0}

    async def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:  # let two iterations run, then break out
            raise asyncio.CancelledError

    monkeypatch.setattr(startup.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await startup._periodic_reflection_loop(agent)

    # Iteration 1: fills (3) != last (-1) → reflect. Iteration 2: unchanged → skip.
    assert agent.reflect_calls == 1


@pytest.mark.asyncio
async def test_periodic_loop_disabled_when_interval_zero(monkeypatch):
    monkeypatch.setattr(settings, "REFLECTION_PERIODIC_SECONDS", 0)
    agent = _FakeReflectionAgent(fills=5)
    # Returns immediately without ever sleeping or reflecting.
    await startup._periodic_reflection_loop(agent)
    assert agent.reflect_calls == 0
