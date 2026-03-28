"""Database initialization utilities for Trading Control."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from api.core.models import Base


async def init_database(database_url: str) -> None:
    """Create all SQLAlchemy-managed tables for the configured database URL."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import os

    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required")

    asyncio.run(init_database(url))
