"""Redis async client helpers."""

from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis

from api.config import settings

_redis_client: Optional[Redis] = None


async def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        redis_url = settings.REDIS_URL or "redis://localhost:6379/0"
        _redis_client = Redis.from_url(
            redis_url, encoding="utf-8", decode_responses=True, max_connections=20
        )
        await _redis_client.ping()
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
