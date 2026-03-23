"""
Shared fixtures for core logic tests.
"""

import pytest_asyncio
from api.database import AsyncSessionLocal, init_database
from tests.conftest import fake_redis, TEST_REFERENCE_DT


@pytest_asyncio.fixture
async def db_session():
    """Provide a fresh database session for core tests."""
    await init_database()
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
