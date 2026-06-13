"""Redis client pool construction — guards the "Too many connections" fix.

The shared async pool must be a BlockingConnectionPool so a request burst WAITS
for a freed connection (up to REDIS_POOL_TIMEOUT_SECONDS) instead of the plain
ConnectionPool's immediate ConnectionError("Too many connections"). The cap must
stay at REDIS_MAX_CONNECTIONS so the Redis plan's client limit is never exceeded.
"""

from __future__ import annotations

from redis.asyncio import BlockingConnectionPool

from api.config import settings
from api.redis_client import _build_pool


def test_build_pool_returns_blocking_pool():
    pool = _build_pool("redis://localhost:6379/0")
    assert isinstance(pool, BlockingConnectionPool), (
        "pool must block (wait) on exhaustion rather than raising 'Too many connections'"
    )


def test_build_pool_respects_max_connections_cap():
    pool = _build_pool("redis://localhost:6379/0")
    assert pool.max_connections == settings.REDIS_MAX_CONNECTIONS


def test_build_pool_sets_wait_timeout():
    pool = _build_pool("redis://localhost:6379/0")
    assert pool.timeout == settings.REDIS_POOL_TIMEOUT_SECONDS
    assert pool.timeout > 0  # a finite wait, not infinite block


def test_default_max_connections_has_headroom_for_blocking_consumers():
    """The single shared pool must outsize the always-on blocking-reader fleet.

    The process runs ~14 ALWAYS-ON blocking stream loops (9 pipeline agents +
    3 challenger agents + the EventPipeline broadcast consumer + the WebSocket
    broadcaster xread loop), each holding a pooled connection ~continuously. At
    the old cap of 20 that left only ~6 connections for request/response traffic
    (REST handlers, heartbeats, price-poller GETs, control-plane reads), so a
    dashboard-refresh burst starved callers past REDIS_POOL_TIMEOUT_SECONDS and
    raised ConnectionError("No connection available"). The cap must keep enough
    headroom above that fleet that a refresh burst is served without waiting.
    If the agent fleet grows past this margin, raise the cap (and confirm the
    Redis plan's client limit) rather than lowering this floor.
    """
    always_on_blocking_loops = 14
    refresh_burst_headroom = 16
    assert settings.REDIS_MAX_CONNECTIONS >= always_on_blocking_loops + refresh_burst_headroom
