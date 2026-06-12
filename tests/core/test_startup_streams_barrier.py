"""Regression tests for the retried Redis streams startup barrier.

The Render deploy crash-looped when a transient pool timeout during
``ensure_all_streams_ready`` (``ConnectionError("No connection available.")``
after ``REDIS_POOL_TIMEOUT_SECONDS``) propagated out of the lifespan: the
gunicorn worker exited with "Worker failed to boot" and the deploy failed.
``_ensure_streams_with_retry`` must absorb transient Redis errors with
backoff and only re-raise after the final attempt — and the lifespan must
pass the barrier before any background task can contend for the pool.
"""

import inspect
import re

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from api import startup as startup_module


@pytest.mark.asyncio
async def test_barrier_retries_transient_connection_error(monkeypatch):
    """One transient ConnectionError must be retried, not crash the boot."""
    calls = []

    async def flaky_barrier(redis_client):
        calls.append(redis_client)
        if len(calls) == 1:
            raise RedisConnectionError("No connection available.")

    sleeps: list[float] = []

    async def instant_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(startup_module, "ensure_all_streams_ready", flaky_barrier)
    monkeypatch.setattr(startup_module.asyncio, "sleep", instant_sleep)

    await startup_module._ensure_streams_with_retry("redis-client")

    assert len(calls) == 2, "barrier must be re-attempted after a transient failure"
    assert sleeps == [2], "first retry must back off before re-attempting"


@pytest.mark.asyncio
async def test_barrier_reraises_after_final_attempt(monkeypatch):
    """A persistent Redis outage must still fail closed after all retries."""
    calls = []

    async def always_failing_barrier(redis_client):
        calls.append(redis_client)
        raise RedisConnectionError("No connection available.")

    async def instant_sleep(seconds):
        return None

    monkeypatch.setattr(startup_module, "ensure_all_streams_ready", always_failing_barrier)
    monkeypatch.setattr(startup_module.asyncio, "sleep", instant_sleep)

    with pytest.raises(RedisConnectionError):
        await startup_module._ensure_streams_with_retry("redis-client")

    assert len(calls) == 4, "1 initial attempt + 3 backoff retries"


@pytest.mark.asyncio
async def test_barrier_succeeds_first_try_without_sleeping(monkeypatch, fake_redis):
    """Happy path: the real barrier passes on attempt 1 with zero backoff."""
    sleeps: list[float] = []
    real_sleep = startup_module.asyncio.sleep

    async def tracking_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(startup_module.asyncio, "sleep", tracking_sleep)

    await startup_module._ensure_streams_with_retry(fake_redis)

    assert sleeps == [], "no backoff sleep on a clean first attempt"


def test_barrier_runs_before_background_pool_users():
    """The lifespan must pass the streams barrier BEFORE starting the gauge
    poller or the LM Studio probe — both contend for the shared Redis
    connection pool, which is exactly what starved the barrier's
    XGROUP CREATE in the crash-looped deploy.
    """
    source = inspect.getsource(startup_module.lifespan)
    barrier = source.index("_ensure_streams_with_retry")
    assert barrier < source.index("start_gauge_poller("), (
        "streams barrier must run before the telemetry gauge poller starts"
    )
    assert barrier < source.index("_probe_lmstudio("), (
        "streams barrier must run before the LM Studio probe"
    )


def test_lmstudio_probe_is_off_the_boot_critical_path():
    """LM Studio is optional — the probe must run as a background task, never
    awaited inline where a slow/absent local-inference host could delay or
    fail startup.
    """
    source = inspect.getsource(startup_module.lifespan)
    assert "await _probe_lmstudio()" not in source, "LM Studio probe must not block the boot path"
    assert re.search(r"create_task\(\s*_probe_lmstudio\(\)", source), (
        "LM Studio probe must run as a fire-and-forget background task"
    )
