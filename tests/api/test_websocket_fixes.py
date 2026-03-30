"""Test WebSocket graceful disconnect handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from api.routes.ws import dashboard_ws


class TestWebSocketFixes:
    """Test that WebSocket handles client disconnections gracefully."""

    @pytest.mark.asyncio
    async def test_websocket_handles_send_json_exception(self):
        """Test that websocket.send_json exceptions are caught and handled."""
        mock_websocket = AsyncMock()
        mock_broadcaster = AsyncMock()
        mock_websocket.app.state.websocket_broadcaster = mock_broadcaster

        # Make send_json raise an exception (simulating disconnected client)
        mock_websocket.send_json.side_effect = Exception("Connection closed")

        # Mock receive_text to cancel after a short time
        async def mock_receive_text():
            await asyncio.sleep(0.1)
            raise asyncio.CancelledError()

        mock_websocket.receive_text = mock_receive_text

        # Should handle the exception gracefully and continue until cancelled
        with pytest.raises(asyncio.CancelledError):
            await dashboard_ws(mock_websocket)

        # Verify broadcaster methods were called
        mock_broadcaster.add_connection.assert_called_once_with(mock_websocket)
        mock_broadcaster.remove_connection.assert_called_once_with(mock_websocket)

    @pytest.mark.asyncio
    async def test_websocket_normal_operation(self):
        """Test that WebSocket works normally when no exceptions occur."""
        mock_websocket = AsyncMock()
        mock_broadcaster = AsyncMock()
        mock_websocket.app.state.websocket_broadcaster = mock_broadcaster

        # Mock receive_text to cancel after a short time
        async def mock_receive_text():
            await asyncio.sleep(0.1)
            raise asyncio.CancelledError()

        mock_websocket.receive_text = mock_receive_text

        # Should handle normally (will be cancelled by mock_receive_text)
        with pytest.raises(asyncio.CancelledError):
            await dashboard_ws(mock_websocket)

        # Verify broadcaster methods were called
        mock_broadcaster.add_connection.assert_called_once_with(mock_websocket)
        mock_broadcaster.remove_connection.assert_called_once_with(mock_websocket)

    @pytest.mark.asyncio
    async def test_websocket_closes_without_broadcaster(self):
        """Test that WebSocket closes gracefully when broadcaster is not available."""
        mock_websocket = AsyncMock()
        mock_websocket.app.state.websocket_broadcaster = None

        await dashboard_ws(mock_websocket)

        # Should have closed the WebSocket
        mock_websocket.close.assert_called_once_with(code=1013)

    def test_websocket_has_broadcaster_pattern(self):
        """Test that the source code contains broadcaster pattern."""
        import inspect

        # Get source code of the function
        ws_source = inspect.getsource(dashboard_ws)

        # Verify the broadcaster pattern is present
        assert "websocket_broadcaster" in ws_source
        assert "add_connection" in ws_source
        assert "remove_connection" in ws_source
