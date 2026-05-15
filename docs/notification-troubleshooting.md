# Troubleshooting Guide

Common breakpoints and how to diagnose them. Add a new section whenever a bug is fixed — document the symptom, root cause, and the regression test that guards against it coming back.

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

---

## Execution engine — score parsing

**Symptom:** Hold decisions from `ReasoningAgent` end up in the DLQ instead of producing an idle heartbeat. Score field contains `"n/a"`.

**Root cause:** `float("n/a")` raises `ValueError`. The engine treated every non-numeric score as a fatal error.

**Fix:** `_as_score()` in `api/services/execution/decision_utils.py` catches parse errors and returns `None`, allowing fallback to the next score key and finally to `0.5`.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_extract_scores_malformed_string_falls_through`

---

**Symptom:** Trades execute at an unintended `signal_confidence = 0.5` even when the decision explicitly set confidence to `0.0`.

**Root cause:** Guard was `if score:` — falsy for Python `float(0.0)`.

**Fix:** `_as_score()` checks `None` and `""` explicitly, so `0.0` is preserved.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_extract_scores_python_float_zero_stays_zero`

---

## System routes — stream lag always showing "Consumer group not found"

**Symptom:** `GET /system/status` → `stream_lag` block shows `"error": "Consumer group not found"` for every stream even while agents are actively processing.

**Root cause:** `get_stream_lag()` was checking for group name `"trading_workers"` but the actual group is `DEFAULT_GROUP = "workers"` (defined in `api/events/bus.py`).

**Fix:** Import and use `DEFAULT_GROUP` — never hardcode the group name.

**Operator check:** `GET /system/status` → `stream_lag` should show `lag_ms` values, not errors.

---

## System routes — trading mode shows TRADING when Redis is unreachable

**Symptom:** `GET /system/trading-mode` returns `{"status": "TRADING"}` even when Redis is down, making it impossible to distinguish "trading is active" from "can't determine status."

**Root cause:** Exception handler fell through to the default TRADING response path.

**Fix:** Exception handler now returns `{"status": "UNKNOWN", "error": "redis_unavailable"}`. Any consumer must treat `UNKNOWN` as "do not trade."

**Operator check:** If Redis is unreachable, `GET /system/trading-mode` must return `status: UNKNOWN`.

---

## Decisions backlog — high count, zero executions

**Symptom:** Dashboard shows hundreds of decisions with zero corresponding executions.

**Likely causes (check in order):**
1. Kill switch is set — `GET /system/trading-mode` returns `KILL_SWITCH`.
2. Circuit breaker is active — same endpoint returns `PAUSED`.
3. `ExecutionEngine` is not running — agent heartbeat shows STALE or OFFLINE.
4. Score gate filtering all decisions — check `signal_confidence` distribution in recent decisions.

**Workaround:** `POST /system/trading-mode {"status": "TRADING"}` clears the circuit breaker. If the kill switch is set it remains active — that requires a separate operator action.
