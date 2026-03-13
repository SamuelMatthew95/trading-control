"""Async database session management for FastAPI runtime."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

try:
    from api.config import get_database_url, settings
except ImportError:  # pragma: no cover
    settings = None

    def get_database_url() -> str:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is required")
        if db_url.startswith("postgres://") or db_url.startswith("postgresql://"):
            return db_url.replace("://", "+asyncpg://", 1)
        return db_url


database_url = get_database_url()
async_engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
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


async def init_database() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
