"""Async database session management for FastAPI runtime."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

try:
    from alembic import command
    from alembic.config import Config as AlembicConfig
except ImportError:  # pragma: no cover
    command = None
    AlembicConfig = None

try:
    from api.config import get_database_url, settings
except ImportError:  # pragma: no cover
    settings = None

    def get_database_url() -> str:
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./trading-control.db")
        if db_url.startswith("postgres://") or db_url.startswith("postgresql://"):
            return db_url.replace("://", "+asyncpg://", 1)
        return db_url


SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///./trading-control.db"
ALEMBIC_STARTUP_LOCK_ID = 78451233


def _resolve_database_url() -> str:
    try:
        return get_database_url()
    except Exception:
        db_url = os.getenv("DATABASE_URL")
        if os.getenv("NODE_ENV", "development") == "production" and not db_url:
            raise RuntimeError("DATABASE_URL is required in production") from None
        return db_url or SQLITE_FALLBACK_URL


def _uses_postgres(url: str) -> bool:
    return url.startswith("postgresql") or url.startswith("postgres")


def _build_alembic_config(url: str):
    if AlembicConfig is None:
        raise RuntimeError("Alembic is required for PostgreSQL schema bootstrap")
    api_dir = Path(__file__).resolve().parent
    config = AlembicConfig(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _run_alembic_upgrade(url: str) -> None:
    if command is None:
        raise RuntimeError("Alembic is required for PostgreSQL schema bootstrap")
    command.upgrade(_build_alembic_config(url), "head")


database_url = _resolve_database_url()


def _engine_kwargs() -> dict:
    """Build SQLAlchemy engine kwargs, skipping pool args for SQLite."""
    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if _uses_postgres(database_url):
        try:
            from api.config import settings as _s

            kwargs["pool_size"] = _s.DB_POOL_SIZE
            kwargs["max_overflow"] = _s.DB_MAX_OVERFLOW
            kwargs["pool_timeout"] = _s.DB_POOL_TIMEOUT
            kwargs["pool_recycle"] = _s.DB_POOL_RECYCLE
        except Exception:
            # Fallback to safe defaults if settings unavailable
            kwargs.update(
                {"pool_size": 5, "max_overflow": 5, "pool_timeout": 30, "pool_recycle": 1800}
            )
    return kwargs


async_engine = create_async_engine(database_url, **_engine_kwargs())
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
AsyncSessionFactory = AsyncSessionLocal
Base = declarative_base()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_async_session() as session:
        yield session


async def init_database() -> None:
    """Runtime helper retained for compatibility tests; app startup does not call this."""
    if _uses_postgres(database_url):
        await _run_alembic_upgrade_with_lock(database_url)
        return

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _run_alembic_upgrade_with_lock(url: str) -> None:
    """Serialize startup migrations across instances to avoid duplicate DDL races."""
    async with async_engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": ALEMBIC_STARTUP_LOCK_ID})
        try:
            await asyncio.to_thread(_run_alembic_upgrade, url)
        finally:
            await conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": ALEMBIC_STARTUP_LOCK_ID}
            )


async def test_database_connection() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_settings_info() -> dict:
    return {
        "config_source": "pydantic_settings" if settings else "environment_variables",
        "database_url": database_url,
        "validation": bool(settings),
    }
