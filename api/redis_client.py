"""Redis async client helpers."""

from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

from api.config import settings
from api.observability import log_structured

_redis_client: Optional[Redis] = None
_redis_pool: Optional[ConnectionPool] = None


async def get_redis() -> Redis:
    global _redis_client, _redis_pool
    if _redis_client is None:
        redis_url = settings.REDIS_URL or "redis://localhost:6379/0"

        # Create connection pool with reasonable limits for hosting
        _redis_pool = ConnectionPool.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=30,  # Conservative limit for hosting environments
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,  # Reap dead connections every 30s
            retry_on_timeout=True,
            retry_on_error=[ConnectionError],
        )

        _redis_client = Redis(connection_pool=_redis_pool)

        # Test connection
        try:
            await _redis_client.ping()
            log_structured("info", "Redis connection established", pool_size=30)
        except (ConnectionError, TimeoutError) as exc:
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
        except (ConnectionError, TimeoutError) as exc:
            log_structured("warning", "Error closing Redis client", exc_info=True)
        finally:
            _redis_client = None

    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
            log_structured("info", "Redis connection pool closed")
        except (ConnectionError, TimeoutError) as exc:
            log_structured("warning", "Error closing Redis pool", exc_info=True)
        finally:
            _redis_pool = None
