"""WebSocket stream offset contract tests."""

from api.constants import (
    STREAM_AGENT_LOGS,
    STREAM_EXECUTIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_NOTIFICATIONS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
)
from api.services.websocket_broadcaster import WebSocketBroadcaster


def test_websocket_stream_offsets_match_supported_streams() -> None:
    """Broadcaster must subscribe to all UI-relevant live streams."""
    broadcaster = WebSocketBroadcaster()
    keys = set(broadcaster._stream_offsets.keys())

    assert keys == {
        STREAM_SIGNALS,
        STREAM_EXECUTIONS,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_AGENT_LOGS,
        STREAM_NOTIFICATIONS,
    }
