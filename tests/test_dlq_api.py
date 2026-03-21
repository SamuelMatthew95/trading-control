"""Test DLQ API endpoints and Redis connection limits."""

from __future__ import annotations

import pytest
try:
    from fastapi.testclient import TestClient
except ImportError:
    from starlette.testclient import TestClient
from unittest.mock import AsyncMock

# Import the FastAPI app
from api.main import app


class TestDLQAPI:
    """Test DLQ API endpoints."""

    def test_get_dlq_empty(self):
        """Test GET /api/dlq with empty DLQ."""
        client = TestClient(app)
        
        # Mock DLQ manager
        mock_dlq = AsyncMock()
        mock_dlq.get_all.return_value = []
        
        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = client.get("/api/dlq", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["items"] == []
            assert data["total"] == 0
            assert data["by_stream"] == {}
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_get_dlq_with_items(self):
        """Test GET /api/dlq with items."""
        client = TestClient(app)
        
        # Mock DLQ manager with items (no datetime objects, just strings)
        mock_items = [
            {"event_id": "abc123", "stream": "orders", "payload": {}, "error": "timeout", "retries": 3},
            {"event_id": "def456", "stream": "orders", "payload": {}, "error": "timeout", "retries": 3},
            {"event_id": "ghi789", "stream": "trades", "payload": {}, "error": "timeout", "retries": 3},
        ]
        
        mock_dlq = AsyncMock()
        mock_dlq.get_all.return_value = mock_items
        
        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = client.get("/api/dlq", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 3
            assert len(data["items"]) == 3
            assert len(data["by_stream"]["orders"]) == 2
            assert len(data["by_stream"]["trades"]) == 1
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_replay_event_success(self):
        """Test POST /api/dlq/{event_id}/replay success."""
        client = TestClient(app)
        
        mock_dlq = AsyncMock()
        mock_dlq.replay.return_value = True
        
        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = client.post("/api/dlq/abc123/replay", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["replayed"] is True
            assert data["event_id"] == "abc123"
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_replay_event_not_found(self):
        """Test POST /api/dlq/{event_id}/replay not found."""
        client = TestClient(app)
        
        mock_dlq = AsyncMock()
        mock_dlq.replay.return_value = False
        
        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = client.post("/api/dlq/abc123/replay", headers={"Host": "localhost"})
            assert response.status_code == 404
            data = response.json()
            assert "not found in DLQ" in data["detail"]
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_clear_event(self):
        """Test DELETE /api/dlq/{event_id}."""
        client = TestClient(app)
        
        mock_dlq = AsyncMock()
        mock_dlq.clear.return_value = None
        
        # Set the dlq_manager on app.state
        app.state.dlq_manager = mock_dlq
        try:
            response = client.delete("/api/dlq/abc123", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["cleared"] is True
            assert data["event_id"] == "abc123"
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_replay_all(self):
        """Test POST /api/dlq/replay-all."""
        client = TestClient(app)
        
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
            response = client.post("/api/dlq/replay-all", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert len(data["replayed"]) == 3
            assert data["replayed"] == ["abc123", "def456", "ghi789"]
            assert len(data["failed"]) == 0
            assert data["total"] == 3
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_clear_all(self):
        """Test DELETE /api/dlq."""
        client = TestClient(app)
        
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
            response = client.delete("/api/dlq", headers={"Host": "localhost"})
            assert response.status_code == 200
            data = response.json()
            assert data["cleared"] == 3
        finally:
            # Clean up
            if hasattr(app.state, 'dlq_manager'):
                delattr(app.state, 'dlq_manager')

    def test_dlq_unavailable_returns_503(self):
        """Test 503 when DLQ manager is not available."""
        client = TestClient(app)
        
        # Ensure dlq_manager doesn't exist
        if hasattr(app.state, 'dlq_manager'):
            delattr(app.state, 'dlq_manager')
        
        response = client.get("/api/dlq", headers={"Host": "localhost"})
        assert response.status_code == 503
        data = response.json()
        assert "DLQ manager not available" in data["detail"]

    def test_redis_max_connections_is_20(self):
        """Test that Redis client has max_connections=20."""
        # Read the source file
        with open('api/redis_client.py', 'r') as f:
            source_code = f.read()
        
        # Check for max_connections=20
        assert 'max_connections=20' in source_code, "Redis client should have max_connections=20"

    def test_dlq_route_registered(self):
        """Test that /api/dlq route is registered."""
        client = TestClient(app)
        
        # Check if the route exists by trying to access it
        # Even if DLQ manager is None, it should return 503, not 404
        # Ensure dlq_manager doesn't exist
        if hasattr(app.state, 'dlq_manager'):
            delattr(app.state, 'dlq_manager')
        
        response = client.get("/api/dlq", headers={"Host": "localhost"})
        assert response.status_code == 503, "Route should be registered and return 503 when DLQ unavailable"
        
        # Also check that the route pattern exists in the app
        route_found = False
        for route in app.routes:
            if hasattr(route, 'path') and '/api/dlq' in route.path:
                route_found = True
                break
        
        assert route_found, "DLQ route not found in registered routes"
