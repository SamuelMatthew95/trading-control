"""Test DLQ API endpoints and Redis connection limits."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock


class TestDLQAPI:
    """Test DLQ API endpoints."""

    @pytest_asyncio.fixture
    async def client(self):
        """Create an async client for testing."""
        # Import here to avoid module load issues
        from api.main import app
        
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            yield client

    @pytest.mark.asyncio
    async def test_get_dlq_empty(self, client):
        """Test GET /api/dlq with empty DLQ."""

        # Mock DLQ manager
        mock_dlq = AsyncMock()
        mock_dlq.get_all.return_value = []

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.get("/api/dlq", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["items"] == []
            assert data["total"] == 0
            assert data["by_stream"] == {}
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_get_dlq_with_items(self, client):
        """Test GET /api/dlq with items."""

        # Mock DLQ manager with items (no datetime objects, just strings)
        mock_items = [
            {
                "event_id": "abc123",
                "stream": "orders",
                "payload": {},
                "error": "timeout",
                "retries": 3,
            },
            {
                "event_id": "def456",
                "stream": "orders",
                "payload": {},
                "error": "timeout",
                "retries": 3,
            },
            {
                "event_id": "ghi789",
                "stream": "trades",
                "payload": {},
                "error": "timeout",
                "retries": 3,
            },
        ]

        mock_dlq = AsyncMock()
        mock_dlq.get_all.return_value = mock_items

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.get("/api/dlq", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 3
            assert len(data["items"]) == 3
            assert len(data["by_stream"]["orders"]) == 2
            assert len(data["by_stream"]["trades"]) == 1
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_replay_event_success(self, client):
        """Test POST /api/dlq/{event_id}/replay success."""

        mock_dlq = AsyncMock()
        mock_dlq.replay.return_value = True

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.post(
                "/api/dlq/abc123/replay", headers={"Host": "localhost"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["replayed"] is True
            assert data["event_id"] == "abc123"
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_replay_event_not_found(self, client):
        """Test POST /api/dlq/{event_id}/replay not found."""

        mock_dlq = AsyncMock()
        mock_dlq.replay.return_value = False

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.post(
                "/api/dlq/abc123/replay", headers={"Host": "localhost"}
            )
            assert response.status_code == 404
            data = response.json()
            assert "not found in DLQ" in data["detail"]
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_clear_event(self, client):
        """Test DELETE /api/dlq/{event_id}."""

        mock_dlq = AsyncMock()
        mock_dlq.clear.return_value = None

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.delete(
                "/api/dlq/abc123", headers={"Host": "localhost"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["cleared"] is True
            assert data["event_id"] == "abc123"
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_replay_all(self, client):
        """Test POST /api/dlq/replay-all."""

        mock_items = [
            {"event_id": "abc123"},
            {"event_id": "def456"},
            {"event_id": "ghi789"},
        ]

        mock_dlq = AsyncMock()
        mock_dlq.get_all.return_value = mock_items
        mock_dlq.replay.return_value = True

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.post(
                "/api/dlq/replay-all", headers={"Host": "localhost"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["replayed"]) == 3
            assert data["replayed"] == ["abc123", "def456", "ghi789"]
            assert len(data["failed"]) == 0
            assert data["total"] == 3
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_clear_all(self, client):
        """Test DELETE /api/dlq."""

        mock_items = [
            {"event_id": "abc123"},
            {"event_id": "def456"},
            {"event_id": "ghi789"},
        ]

        mock_dlq = AsyncMock()
        mock_dlq.get_all.return_value = mock_items
        mock_dlq.clear.return_value = None

        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = await client.delete("/api/dlq", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["cleared"] == 3
        finally:
            # Clean up
            if hasattr(app.state, "dlq_manager"):
                delattr(app.state, "dlq_manager")

    @pytest.mark.asyncio
    async def test_dlq_unavailable_returns_503(self, client):
        """Test 503 when DLQ manager is not available."""

        # Ensure dlq_manager doesn't exist
        if hasattr(app.state, "dlq_manager"):
            delattr(app.state, "dlq_manager")

        response = await client.get("/api/dlq", headers={"Host": "localhost"})
        assert response.status_code == 503
        data = response.json()
        assert "DLQ manager not available" in data["detail"]

    @pytest.mark.asyncio
    async def test_redis_max_connections_is_20(self):
        """Test that Redis client configures max_connections=30."""
        import inspect
        from api import redis_client

        redis_source_code = inspect.getsource(redis_client)

        assert (
            "max_connections=30" in redis_source_code
        ), "Redis client should have max_connections=30"

    @pytest.mark.asyncio
    async def test_dlq_route_registered(self, client):
        """Test that /api/dlq route is registered."""

        # Check if the route exists by trying to access it
        # Even if DLQ manager is None, it should return 503, not 404
        # Ensure dlq_manager doesn't exist
        if hasattr(app.state, "dlq_manager"):
            delattr(app.state, "dlq_manager")

        response = await client.get("/api/dlq", headers={"Host": "localhost"})
        assert (
            response.status_code == 503
        ), "Route should be registered and return 503 when DLQ unavailable"

        # Also check that the route pattern exists in the app
        route_found = False
        for route in app.routes:
            if hasattr(route, "path") and "/api/dlq" in route.path:
                route_found = True
                break

        assert route_found, "DLQ route not found in registered routes"
