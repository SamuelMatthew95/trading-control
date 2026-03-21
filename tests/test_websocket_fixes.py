"""Test WebSocket graceful disconnect handling."""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from api.routes.ws import dashboard_ws


class TestWebSocketFixes:
    """Test that WebSocket handles client disconnections gracefully."""

    @pytest.mark.asyncio
    async def test_websocket_handles_send_json_exception(self):
        """Test that websocket.send_json exceptions are caught and handled."""
        mock_websocket = AsyncMock()
        mock_websocket.app.state.redis_client = AsyncMock()

        # Mock xread to return test data on first call, then empty on subsequent calls
        test_message = (
            b"test_stream",
            [
                (
                    b"123456789",
                    {
                        b"payload": json.dumps(
                            {"type": "test", "data": "value"}
                        ).encode()
                    },
                )
            ],
        )

        call_count = 0

        async def mock_xread(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [test_message]
            else:
                return []  # No more messages

        mock_websocket.app.state.redis_client.xread = mock_xread

        # Make send_json raise an exception (simulating disconnected client)
        mock_websocket.send_json.side_effect = Exception("Connection closed")

        # Mock sleep to cancel after a few iterations
        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)
            if len(sleep_calls) >= 2:  # Allow a couple iterations then cancel
                raise asyncio.CancelledError()

        with pytest.MonkeyPatch().context() as m:
            m.setattr("api.routes.ws.asyncio.sleep", mock_sleep)

            # Should handle the exception gracefully and continue until cancelled
            with pytest.raises(asyncio.CancelledError):
                await dashboard_ws(mock_websocket)

        # Verify send_json was called and exception was handled
        mock_websocket.send_json.assert_called_once()
        assert call_count >= 1  # xread was called at least once

    @pytest.mark.asyncio
    async def test_websocket_normal_operation(self):
        """Test that WebSocket works normally when no exceptions occur."""
        mock_websocket = AsyncMock()
        mock_websocket.app.state.redis_client = AsyncMock()

        # Mock xread to return empty (no messages)
        mock_websocket.app.state.redis_client.xread.return_value = []

        # Mock sleep to exit after one iteration
        with pytest.MonkeyPatch().context() as m:

            async def mock_sleep(*args, **kwargs):
                # Cancel the task after one iteration
                raise asyncio.CancelledError()

            m.setattr("api.routes.ws.asyncio.sleep", mock_sleep)

            # Should handle normally (will be cancelled by mock_sleep)
            with pytest.raises(asyncio.CancelledError):
                await dashboard_ws(mock_websocket)

    def test_websocket_has_try_catch_around_send_json(self):
        """Test that the source code contains try/catch around send_json."""
        import inspect

        # Get source code of the function
        ws_source = inspect.getsource(dashboard_ws)

        # Verify the try/except pattern is present
        assert "try:" in ws_source
        assert "await websocket.send_json(payload)" in ws_source
        assert "except Exception:" in ws_source
        assert "break" in ws_source
