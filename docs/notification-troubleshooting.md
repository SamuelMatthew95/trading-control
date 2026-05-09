# Notification Troubleshooting (Dashboard)

This checklist documents the end-to-end path for buy/sell notifications and the
most common breakpoints.

## Live path

1. `ExecutionEngine` publishes `type=order_filled` events to `executions`.
2. `NotificationAgent` converts fills to `trade.*_filled` notifications and
   publishes to `notifications`.
3. `WebSocketBroadcaster` **must** subscribe to `notifications` in
   `_stream_offsets` and pass displayable payloads through.
4. Frontend websocket hook (`useGlobalWebSocket`) appends notifications into the
   store.

If step 3 is missing, users often report: "I see one startup notification but no
new buy/sell notifications."

## Required invariants

- `WebSocketBroadcaster._stream_offsets` includes `STREAM_NOTIFICATIONS`.
- `NotificationAgent` dedup key uses a stable identifier even when trace fields
  are missing (fallback to Redis stream entry id).
- Notification payloads include both:
  - non-empty `notification_type`
  - non-empty `message`

## Regression tests that must stay green

- `tests/core/test_websocket_notifications_regression.py`
- `tests/agents/test_notification_agent.py`
- `tests/core/test_websocket_stream_offsets.py::test_websocket_stream_offsets_match_supported_streams`

## Operator checks

- Confirm the Agents dashboard shows notification agent heartbeat updates.
- Confirm websocket status is connected.
- Confirm `notifications` stream length increases while trades execute.


## PnL and UI data contract checks

For trade notifications, the backend should include these fields when available:

- `qty`
- `fill_price`
- `notional`
- `pnl`
- `pnl_percent`

The websocket broadcaster forwards notification payloads as-is for displayable
notifications, and the frontend websocket hook maps those fields into the
notification store for rendering in dashboard cards and feed rows.

Important: notification delivery and PnL summary charts are related but separate
paths. A temporary notification issue should not be assumed to mean core PnL
aggregation is wrong; verify both paths independently.
