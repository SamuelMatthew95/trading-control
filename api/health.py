"""
Health check endpoints for container deployment
"""

from fastapi import APIRouter
from api.redis_client import get_redis, close_redis
from api.database import AsyncSessionFactory

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check for container orchestrators."""
    try:
        # Check Redis
        redis = await get_redis()
        await redis.ping()
        await close_redis()

        # Check PostgreSQL
        async with AsyncSessionFactory() as session:
            await session.execute("SELECT 1")

        return {"status": "healthy", "redis": "ok", "postgres": "ok"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 503
