"""Redis stream initialization utility."""

from __future__ import annotations

import asyncio
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from api.constants import (
    STREAM_EXECUTIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_ORDERS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
)
from api.observability import log_structured
from api.redis_client import get_redis

# All streams used in the application
ALL_STREAMS = [
    STREAM_MARKET_TICKS,      # "market_ticks"
    STREAM_SIGNALS,           # "signals" 
    STREAM_ORDERS,            # "orders"
    STREAM_EXECUTIONS,        # "executions"
    STREAM_RISK_ALERTS,       # "risk_alerts"
    STREAM_LEARNING_EVENTS,   # "learning_events"
    STREAM_SYSTEM_METRICS,    # "system_metrics"
]

# Consumer groups that need to be created
DEFAULT_GROUP = "workers"


async def ensure_redis_streams(redis_client: Optional[Redis] = None) -> None:
    """
    Ensure all Redis streams and consumer groups exist.
    
    This function creates all required streams and consumer groups if they don't exist.
    It handles BUSYGROUP errors silently (group already exists) and logs the outcome.
    
    Args:
        redis_client: Optional Redis client. If None, will create a new connection.
    """
    if redis_client is None:
        redis_client = await get_redis()
    
    created_count = 0
    existing_count = 0
    
    log_structured("info", "Ensuring Redis streams and consumer groups exist")
    
    for stream in ALL_STREAMS:
        try:
            # Create the stream and consumer group
            # Handle both sync and async Redis clients
            result = redis_client.xgroup_create(
                stream, 
                DEFAULT_GROUP, 
                id="$",  # Use "$" for trading systems - only process new messages
                mkstream=True
            )
            
            # If result is a coroutine, await it
            if asyncio.iscoroutine(result):
                await result
                
            created_count += 1
            log_structured("info", "Created Redis stream and group", stream=stream, group=DEFAULT_GROUP)
            
        except ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                existing_count += 1
                log_structured("debug", "Redis stream and group already exist", stream=stream, group=DEFAULT_GROUP)
            else:
                # Re-raise unexpected Redis errors
                log_structured("error", "Failed to create Redis stream group", stream=stream, group=DEFAULT_GROUP, error=str(exc))
                raise
        except Exception as exc:
            log_structured("error", "Unexpected error creating Redis stream group", stream=stream, group=DEFAULT_GROUP, error=str(exc))
            raise
    
    log_structured(
        "info", 
        "Redis stream initialization complete", 
        created_streams=created_count,
        existing_streams=existing_count,
        total_streams=len(ALL_STREAMS)
    )


def main() -> None:
    """CLI entry point for manual Redis initialization."""
    async def _init():
        try:
            await ensure_redis_streams()
            print("✅ Redis streams initialized successfully")
        except Exception as exc:
            print(f"❌ Failed to initialize Redis streams: {exc}")
            raise
    
    asyncio.run(_init())


if __name__ == "__main__":
    main()
