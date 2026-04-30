from api.services.websocket_broadcaster import WebSocketBroadcaster


def test_broadcaster_suppresses_legacy_notification_payloads():
    broadcaster = WebSocketBroadcaster()

    assert (
        broadcaster._transform_stream_message(
            "notifications",
            "1-0",
            {
                "notification_type": "stream:agent_logs",
                "stream_source": "agent_logs",
                "severity": "INFO",
                "message": "agent_logs:agent_log - hold",
            },
        )
        is None
    )
    assert (
        broadcaster._transform_stream_message(
            "notifications",
            "1-1",
            {
                "notification_type": "decision.hold",
                "stream_source": "decisions",
                "severity": "INFO",
                "message": "DECISION - SPY | HOLD",
            },
        )
        is None
    )


def test_broadcaster_keeps_trade_notifications_and_decodes_display_json():
    broadcaster = WebSocketBroadcaster()
    decoded = broadcaster._decode_redis_payload(
        {
            b"notification_type": b"trade.buy_filled",
            b"stream_source": b"executions",
            b"severity": b"INFO",
            b"message": b"BUY BTC/USD filled",
            b"display": b'{"kind":"trade_execution","title":"BUY filled: BTC/USD"}',
        }
    )

    outbound = broadcaster._transform_stream_message("notifications", "2-0", decoded)

    assert outbound is not None
    assert outbound["notification_type"] == "trade.buy_filled"
    assert outbound["display"]["kind"] == "trade_execution"
