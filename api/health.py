"""
Health check endpoints for container deployment
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from api.redis_client import get_redis, close_redis
from api.database import AsyncSessionFactory

logger = logging.getLogger(__name__)
router = APIRouter()

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


async def safe_redis_check():
    """Safe Redis health check with timeout and graceful degradation."""
    try:
        redis = await asyncio.wait_for(get_redis(), timeout=2.0)
        await asyncio.wait_for(redis.ping(), timeout=2.0)
        await close_redis()
        return True
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return False


async def safe_database_check():
    """Safe database health check with timeout and graceful degradation."""
    try:
        async with AsyncSessionFactory() as session:
            await asyncio.wait_for(session.execute("SELECT 1"), timeout=2.0)
        return True
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False


@router.get("/health")
async def health_check():
    """Health check for container orchestrators."""
    now = datetime.now(timezone.utc)
    
    # Check startup grace period (60 seconds)
    uptime_seconds = (now - PROCESS_START_TIME).total_seconds()
    if uptime_seconds < 60:
        return {
            "status": "starting",
            "message": "Service is warming up",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat()
        }
    
    # Check dependencies with graceful degradation
    redis_ok = await safe_redis_check()
    db_ok = await safe_database_check()
    
    if redis_ok and db_ok:
        return {
            "status": "healthy",
            "redis": "ok",
            "postgres": "ok",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat()
        }
    else:
        return {
            "status": "degraded",
            "message": "Some dependencies are unavailable",
            "redis": "ok" if redis_ok else "unavailable",
            "postgres": "ok" if db_ok else "unavailable",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat()
        }
