"""Regression tests for live notification websocket delivery."""

from api.constants import STREAM_NOTIFICATIONS
from api.services.websocket_broadcaster import WebSocketBroadcaster


def test_broadcaster_subscribes_notifications_stream() -> None:
    """Notifications stream must be in xread offsets for live pushes."""
    broadcaster = WebSocketBroadcaster()
    assert STREAM_NOTIFICATIONS in broadcaster._stream_offsets


def test_transform_notifications_trade_payload_is_forwarded() -> None:
    """Displayable trade notifications should pass through to websocket clients."""
    broadcaster = WebSocketBroadcaster()
    payload = {
        "notification_type": "trade.buy_filled",
        "message": "BUY BTC/USD filled",
        "source": "notification_agent",
        "symbol": "BTC/USD",
        "side": "buy",
    }

    result = broadcaster._transform_stream_message(STREAM_NOTIFICATIONS, "1-0", payload)

    assert result is not None
    assert result["stream"] == STREAM_NOTIFICATIONS
    assert result["notification_type"] == "trade.buy_filled"
    assert result["message"] == "BUY BTC/USD filled"


def test_transform_notifications_hidden_payload_is_filtered() -> None:
    """Non-user-facing internal notifications must still be filtered."""
    broadcaster = WebSocketBroadcaster()
    payload = {
        "notification_type": "signal.generated",
        "message": "internal signal",
        "source": "signals",
    }

    result = broadcaster._transform_stream_message(STREAM_NOTIFICATIONS, "2-0", payload)

    assert result is None


def test_transform_notifications_preserves_trade_metrics() -> None:
    """Trade metrics (qty/fill/notional/pnl) must survive ws transformation."""
    broadcaster = WebSocketBroadcaster()
    payload = {
        "notification_type": "trade.sell_filled",
        "message": "SELL BTC/USD filled",
        "source": "notification_agent",
        "symbol": "BTC/USD",
        "side": "sell",
        "qty": 0.5,
        "fill_price": 60500.0,
        "notional": 30250.0,
        "pnl": -125.75,
        "pnl_percent": -0.42,
    }

    result = broadcaster._transform_stream_message(STREAM_NOTIFICATIONS, "3-0", payload)

    assert result is not None
    assert result["qty"] == 0.5
    assert result["fill_price"] == 60500.0
    assert result["notional"] == 30250.0
    assert result["pnl"] == -125.75
    assert result["pnl_percent"] == -0.42
