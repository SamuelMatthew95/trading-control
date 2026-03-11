"""
Production Database Session Manager
Handles async SQLAlchemy sessions with proper transaction management for Vercel serverless
Uses Pydantic settings for robust configuration validation
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Import settings with Pydantic validation
try:
    from config import get_database_url, settings
except ImportError:
    print("⚠️  config.py not found, using fallback configuration")
    settings = None
    get_database_url = lambda: os.getenv("DATABASE_URL")

if settings:
    # Use validated settings from Pydantic
    database_url = get_database_url()
    if not database_url:
        raise ValueError(
            "DATABASE_URL is required and must be a valid PostgreSQL connection string"
        )

    # Create async engine for serverless compatibility
    async_engine = create_engine(database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
else:
    # Fallback for development without config.py
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")

    # Create async engine for serverless compatibility
    async_database_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    async_engine = create_engine(async_database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

# Create declarative base
Base = declarative_base()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions with proper error handling"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_database():
    """Initialize database tables"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_database_connection() -> bool:
    """Test database connection"""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


def get_settings_info():
    """Get current settings information for debugging"""
    if settings:
        return {
            "config_source": "pydantic_settings",
            "database_url": get_database_url(),
            "validation": "enabled",
        }
    else:
        return {
            "config_source": "environment_variables",
            "database_url": os.getenv("DATABASE_URL"),
            "validation": "disabled",
        }
