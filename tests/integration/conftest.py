"""
Shared fixtures for integration tests.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from api.database import AsyncSessionLocal, init_database
from api.main import app
from tests.core.conftest import db_session
from tests.conftest import fake_redis


@pytest_asyncio.fixture
async def api_client():
    """Provide an async HTTP client for integration testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def integrated_setup(db_session, api_client):
    """Provide both database session and API client for full integration tests."""
    yield {"session": db_session, "client": api_client}
