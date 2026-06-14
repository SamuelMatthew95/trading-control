"""Periodic reflection safety-net loop (api/startup._periodic_reflection_loop).

The loop delegates all gating (cooldown / new-data / min-fills) to the agent's
``maybe_reflect``; here we only assert the loop drives it on the interval, keeps
going on error, and is disabled when the interval is 0.
"""

from __future__ import annotations

import asyncio

import pytest

from api import startup
from api.config import settings


class _FakeReflectionAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def maybe_reflect(self) -> bool:
        self.calls += 1
        return True


@pytest.mark.asyncio
async def test_periodic_loop_drives_maybe_reflect_each_tick(monkeypatch):
    monkeypatch.setattr(settings, "REFLECTION_PERIODIC_SECONDS", 1)
    agent = _FakeReflectionAgent()

    sleeps = {"n": 0}

    async def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:  # let two iterations run, then break out
            raise asyncio.CancelledError

    monkeypatch.setattr(startup.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await startup._periodic_reflection_loop(agent)

    assert agent.calls == 2


@pytest.mark.asyncio
async def test_periodic_loop_survives_maybe_reflect_error(monkeypatch):
    """A reflection error must not kill the loop."""
    monkeypatch.setattr(settings, "REFLECTION_PERIODIC_SECONDS", 1)

    class _Boom:
        def __init__(self):
            self.calls = 0

        async def maybe_reflect(self):
            self.calls += 1
            raise RuntimeError("boom")

    agent = _Boom()
    sleeps = {"n": 0}

    async def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(startup.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await startup._periodic_reflection_loop(agent)
    assert agent.calls == 2  # kept going despite the error


@pytest.mark.asyncio
async def test_periodic_loop_disabled_when_interval_zero(monkeypatch):
    monkeypatch.setattr(settings, "REFLECTION_PERIODIC_SECONDS", 0)
    agent = _FakeReflectionAgent()
    await startup._periodic_reflection_loop(agent)  # returns immediately
    assert agent.calls == 0
