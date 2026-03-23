"""
Shared fixtures for API tests.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from api.main import app
from tests.conftest import fake_redis


@pytest_asyncio.fixture
async def api_client():
    """Provide an async HTTP client for API testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
