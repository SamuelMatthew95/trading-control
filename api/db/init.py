"""Database initialization utilities for non-production bootstrap flows."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from api.core.models import Base


async def init_database(database_url: str) -> None:
    """Create SQLAlchemy tables for SQLite/local use.

    Production PostgreSQL environments should run Alembic migrations instead of
    `metadata.create_all` to preserve schema history and migration safety.
    """
    if database_url.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
        raise RuntimeError(
            "PostgreSQL bootstrap must use Alembic migrations (do not call create_all in production)."
        )

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
