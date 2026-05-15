# System Routes Troubleshooting

## Stream lag always shows "Consumer group not found"

**Symptom:** `GET /system/status` → `stream_lag` reports `"error": "Consumer group not found"` for every stream, even while agents are actively processing.

**Root cause:** `get_stream_lag()` was checking for group name `"trading_workers"` but the actual group is `DEFAULT_GROUP = "workers"` (defined in `api/events/bus.py`).

**Fix:** Import and use `DEFAULT_GROUP` — never hardcode the group name string.

**Operator check:** After the fix, `GET /system/status` → `stream_lag` should show numeric `lag_ms` values, not errors.

---

## Trading mode shows TRADING when Redis is unreachable

**Symptom:** `GET /system/trading-mode` returns `{"status": "TRADING"}` when Redis is down. Impossible to distinguish "trading is active" from "state unknown."

**Root cause:** The exception handler fell through to the default TRADING response path (fail-open).

**Fix:** Exception handler now returns `{"status": "UNKNOWN", "error": "redis_unavailable"}`. Any consumer must treat `UNKNOWN` as "do not trade."

**Operator check:** With Redis unreachable, `GET /system/trading-mode` must return `status: UNKNOWN`.

---

## DB session created in memory mode

**Symptom:** `GET /system/status`, `GET /system/logs`, or `GET /system/metrics` raise a connection error when `USE_MEMORY_MODE=true` or when PostgreSQL is unavailable.

**Root cause:** Routes created an `AsyncSession` unconditionally instead of checking `is_db_available()` first.

**Fix:** All three routes now gate on `is_db_available()` and return a safe memory-mode payload when the DB is not up.

**Rule:** Any route that reads from PostgreSQL must check `is_db_available()` before calling `_make_session()` or any session factory. If it can serve from `get_runtime_store()`, it must.
