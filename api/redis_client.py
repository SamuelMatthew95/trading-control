"""Redis async client helpers."""

from __future__ import annotations

import traceback
from typing import Optional

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError, TimeoutError

from api.config import settings
from api.observability import log_structured

_redis_client: Optional[Redis] = None
_redis_pool: Optional[ConnectionPool] = None


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
            log_structured(
                "error",
                "redis_url_missing",
                event_name="redis_url_missing",
                msg="REDIS_URL env variable not set",
            )
            raise RuntimeError("Missing REDIS_URL")

        _redis_pool = ConnectionPool.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=30,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True,
            retry_on_error=[ConnectionError],
        )
        _redis_client = Redis(connection_pool=_redis_pool)

        try:
            await _redis_client.ping()
            log_structured(
                "info",
                "redis_connected",
                event_name="redis_connected",
                url_masked=_mask_redis_url(redis_url),
            )
        except (ConnectionError, TimeoutError) as exc:
            log_structured(
                "error",
                "redis_connection_failed",
                event_name="redis_connection_failed",
                exc_info=True,
                traceback=traceback.format_exc(),
            )
            await close_redis()
            raise RuntimeError("Cannot connect to Redis") from exc
    return _redis_client


async def close_redis() -> None:
    global _redis_client, _redis_pool
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            log_structured("info", "redis_client_closed")
        finally:
            _redis_client = None

    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
            log_structured("info", "redis_pool_closed")
        finally:
            _redis_pool = None
