"""
Shared fixtures for integration tests.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest_asyncio.fixture
async def api_client():
    """Provide an async HTTP client for integration testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def integrated_setup(db_session, api_client):
    """Provide both database session and API client for full integration tests."""
    yield {"session": db_session, "client": api_client}
