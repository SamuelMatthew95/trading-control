from __future__ import annotations

import os
import asyncio
from datetime import datetime

import fakeredis
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

os.environ["ENABLE_SIGNAL_SCHEDULER"] = "false"

TEST_REFERENCE_DT = datetime(2024, 6, 15, 12, 0, 0)

# Test database URL - use environment variable or default to Docker PostgreSQL
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5433/test_trading"
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        pool_size=5,
        max_overflow=10
    )
    
    # Create extensions and tables in a fresh connection
    async with engine.connect() as conn:
        # Enable required extensions
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.commit()
    
    # Drop and recreate tables
    async with engine.begin() as conn:
        # Import and create tables
        from api.core.models import Base
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Cleanup
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Create session factory for tests."""
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False
    )
    return factory


@pytest_asyncio.fixture
async def db_session(session_factory):
    """Provide a database session for tests."""
    async with session_factory() as session:
        yield session
        # Cleanup after test
        await session.rollback()


@pytest_asyncio.fixture
async def safe_writer(session_factory):
    """Provide a SafeWriter instance."""
    from api.core.safe_writer import SafeWriter
    return SafeWriter(session_factory)


@pytest_asyncio.fixture
async def test_strategy(db_session):
    """Create a test strategy for order tests."""
    from api.core.models import Strategy
    
    strategy = Strategy(
        name="test_strategy",
        description="Test strategy for unit tests",
        config={},
        schema_version="v2",
        source="test_service_v2",
        status="active"
    )
    db_session.add(strategy)
    await db_session.flush()
    await db_session.refresh(strategy)
    return strategy


@pytest_asyncio.fixture
async def fake_redis():
    """Provide a fresh fakeredis async instance for each test."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield redis
    await redis.aclose()
