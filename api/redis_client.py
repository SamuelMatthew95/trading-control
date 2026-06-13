"""Redis async client helpers."""

from __future__ import annotations

from redis.asyncio import BlockingConnectionPool, ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from api.config import settings
from api.constants import FieldName
from api.observability import log_structured

_redis_client: Redis | None = None
_redis_pool: ConnectionPool | None = None


def _build_pool(redis_url: str) -> BlockingConnectionPool:
    """Build the shared async Redis pool.

    A ``BlockingConnectionPool`` makes a caller WAIT up to
    ``REDIS_POOL_TIMEOUT_SECONDS`` for a free connection when the pool is
    saturated, instead of the plain ``ConnectionPool``'s immediate
    ``ConnectionError("Too many connections")``. Background blocking reads
    (``xread`` / ``xreadgroup``) hold pooled connections during their block
    window, so a dashboard refresh firing many REST endpoints at once would
    otherwise drain the pool and raise. The cap stays at
    ``REDIS_MAX_CONNECTIONS`` so the Redis plan's client limit is never exceeded.
    """
    return BlockingConnectionPool.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        timeout=settings.REDIS_POOL_TIMEOUT_SECONDS,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
        retry_on_timeout=True,
        retry_on_error=[RedisConnectionError],
    )


def redis_pool_stats() -> dict[str, int | bool] | None:
    """Point-in-time stats of the shared pool — pure in-process, NO Redis I/O.

    Because this reads only local counters, it stays readable even when the
    pool is fully saturated — which is exactly when it matters: saturation
    starves callers on ``BlockingConnectionPool.get_connection`` and every
    actual Redis command (including health-check pings) stalls or raises
    ``ConnectionError("No connection available.")``. Surfaced on ``/health``
    so chronic saturation is visible at a glance instead of only as
    intermittent consume warnings in the logs.

    ``in_use_connections == max_connections`` is the saturation signature.

    Returns ``None`` before ``get_redis()`` has built the pool. Reads
    redis-py's private counters (``_in_use_connections`` /
    ``_available_connections``) defensively — absent attributes degrade to 0,
    never raise (pinned to redis-py 5.0.1 internals; the regression test
    asserts the attributes exist on the real pool class).
    """
    pool = _redis_pool
    if pool is None:
        return None
    max_connections = int(getattr(pool, "max_connections", 0) or 0)
    in_use = len(getattr(pool, "_in_use_connections", ()) or ())
    return {
        FieldName.MAX_CONNECTIONS: max_connections,
        FieldName.IN_USE_CONNECTIONS: in_use,
        FieldName.IDLE_CONNECTIONS: len(getattr(pool, "_available_connections", ()) or ()),
        FieldName.SATURATED: max_connections > 0 and in_use >= max_connections,
    }


def _mask_redis_url(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.split("@", 1)
    if ":" in prefix:
        scheme_and_user = prefix.rsplit(":", 1)[0]
        return f"{scheme_and_user}:****@{suffix}"
    return f"****@{suffix}"


async def get_redis() -> Redis:
    global _redis_client, _redis_pool
    if _redis_client is None:
        redis_url = settings.REDIS_URL
        if not redis_url:
            log_structured("error", "redis_url_missing", event_name="redis_url_missing")
            raise RuntimeError("Missing REDIS_URL")

        _redis_pool = _build_pool(redis_url)
        _redis_client = Redis(connection_pool=_redis_pool)

        try:
            await _redis_client.ping()
            log_structured(
                "info",
                "redis_connected",
                event_name="redis_connected",
                url_masked=_mask_redis_url(redis_url),
            )
        except (RedisConnectionError, RedisTimeoutError):
            log_structured("error", "Redis connection failed", exc_info=True)
            await close_redis()
            raise
    return _redis_client


async def close_redis() -> None:
    global _redis_client, _redis_pool
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            log_structured("info", "Redis client closed")
        except (RedisConnectionError, RedisTimeoutError):
            log_structured("warning", "Error closing Redis client", exc_info=True)
        finally:
            _redis_client = None

    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
            log_structured("info", "Redis connection pool closed")
        except (RedisConnectionError, RedisTimeoutError):
            log_structured("warning", "Error closing Redis pool", exc_info=True)
        finally:
            _redis_pool = None
