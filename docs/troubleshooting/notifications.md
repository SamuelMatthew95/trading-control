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

## Dedup test used different stream msg IDs but no trace_id

**Symptom:** `test_deduplication_skips_repeat` failed — second notification was forwarded even though the event content was identical.

**Root cause:** The dedup key includes `trace_key`, which falls back to the Redis stream message ID when neither `trace_id` nor `msg_id` is present in the event payload. Sending two events with `redis_id="id-1"` and `redis_id="id-2"` produced two distinct dedup keys, so dedup was correctly NOT triggered, but the test expected it to be.

**Fix:** Updated the test event to include a shared `trace_id`. Same `stream+type+side+symbol+trace_id` → same dedup key → second event is suppressed as intended. (`tests/agents/test_notification_agent.py:107`)

**Regression test:** `tests/agents/test_notification_agent.py::test_deduplication_skips_repeat`

---

## WebSocket broadcaster logged into the void with zero clients connected

**Symptom:** Logs repeatedly show `websocket_broadcast` with `"active_connections": 0` while the pipeline is otherwise healthy — the backend "broadcasts" every Redis stream message even though no browser/dashboard is attached. (The `active_connections: 0` is expected when no client is connected; the wasted work + log spam is the actual issue.)

**Root cause:** `WebSocketBroadcaster.broadcast()` had no zero-client guard. With no connections it still extracted payload fields, iterated an (empty) connection set, and emitted the per-message `websocket_broadcast` log. The sibling `_agent_status_push_loop` already guarded (`if not self._connections: continue`); the broadcast path did not.

**Fix:** Early-return at the top of `broadcast()` when `self._connections` is empty (`api/services/websocket_broadcaster.py`). The dashboard `xread` loop keeps running so the stream cursor stays warm — the next client to connect immediately receives live data.

**Regression test:** `tests/core/test_websocket_broadcaster.py::test_broadcast_noop_when_no_connections`

---

## Regression tests

- `tests/core/test_websocket_notifications_regression.py`
- `tests/agents/test_notification_agent.py`
- `tests/core/test_websocket_stream_offsets.py::test_websocket_stream_offsets_match_supported_streams`
- `tests/core/test_websocket_broadcaster.py::test_broadcast_noop_when_no_connections`

## Notification timestamp renders as a raw epoch float ("1780634112.7714157")

**Symptom:** The Notifications panel header and some rows (e.g. the "startup"
in-memory-fallback notice) showed a raw number like `1780634112.7714157` instead
of a relative time. Other notifications with ISO timestamps showed "12h ago"
correctly, so the panel looked half-broken / untrustworthy.

**Root cause:** `NotificationFeed.formatRelativeTime` parsed strings with
`Date.parse`, which returns `NaN` for a float epoch-seconds string. The
`if (!isFinite(ts)) return value` guard then returned the **raw value**, which
rendered verbatim. (Producers are inconsistent: some emit ISO strings, the
startup notice emits `time.time()` epoch seconds.)

**Fix:** `NotificationFeed.tsx` — `formatRelativeTime` now routes through the
shared `parseTimestampMs` (handles epoch-seconds / epoch-ms / numeric-string /
ISO via the `EPOCH_MS_THRESHOLD` boundary) and collapses unparseable/missing
input to the `--` fallback instead of echoing the raw value. Function exported
for regression testing.

**Regression test:** `frontend/src/test/components/notification-feed.test.ts` —
`renders a float epoch-seconds string as relative time, not the raw value`.
