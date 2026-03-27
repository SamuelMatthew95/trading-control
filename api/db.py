"""Compatibility DB module that re-exports the canonical async database runtime.

This module keeps the historical ``api.db`` import path stable while delegating
all session and engine configuration to ``api.database``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, async_engine

# Backwards-compatible aliases expected throughout the codebase.
engine = async_engine
AsyncSessionFactory = AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async SQLAlchemy session."""
    async with AsyncSessionFactory() as session:
        yield session
