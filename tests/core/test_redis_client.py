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
