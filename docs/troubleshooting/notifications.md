# Notifications Troubleshooting

## Live delivery path

1. `ExecutionEngine` publishes `type=order_filled` to the `executions` stream.
2. `NotificationAgent` converts fills to `trade.*_filled` notifications and publishes to `notifications`.
3. `WebSocketBroadcaster` must subscribe to `notifications` in `_stream_offsets` and forward displayable payloads.
4. Frontend `useGlobalWebSocket` appends notifications into the store.

If step 3 is missing, the symptom is: "I see one startup notification but no new buy/sell notifications."

## Required invariants

- `WebSocketBroadcaster._stream_offsets` includes `STREAM_NOTIFICATIONS`.
- `NotificationAgent` dedup key uses a stable identifier even when trace fields are missing (fallback to Redis stream entry id).
- Notification payloads must include non-empty `notification_type` and `message`.

## PnL fields in trade notifications

When available, fill notifications should carry:

- `qty`
- `fill_price`
- `notional`
- `pnl`
- `pnl_percent`

The WebSocket broadcaster forwards payloads as-is; the frontend maps those fields into dashboard cards and feed rows.

Note: notification delivery and PnL summary charts are separate paths. A notification gap does not mean PnL aggregation is wrong — verify both independently.

## Operator checks

- Agent dashboard shows NotificationAgent heartbeat updating.
- WebSocket status is connected.
- `notifications` stream length increases while trades execute.

## Regression tests

- `tests/core/test_websocket_notifications_regression.py`
- `tests/agents/test_notification_agent.py`
- `tests/core/test_websocket_stream_offsets.py::test_websocket_stream_offsets_match_supported_streams`
