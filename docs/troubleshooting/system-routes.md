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

---

## test_flow_status_not_degraded_when_db_available patches wrong module after dashboard refactor

**Symptom:** `test_flow_status_not_degraded_when_db_available` failed with `AttributeError: module 'api.routes.dashboard_v2' has no attribute 'is_db_available'`.

**Root cause:** After the dashboard route was refactored to delegate to `api.services.dashboard.flow.get_flow_status_payload()`, `is_db_available` and `AsyncSessionFactory` are imported in the `flow` service module, not in `dashboard_v2`. The test was still patching them on `dashboard_v2`.

**Fix:** Updated the test to import and patch `api.services.dashboard.flow` for both `is_db_available` and `AsyncSessionFactory`. (`tests/agents/test_pipeline_handoff.py:385`)

**Regression test:** `tests/agents/test_pipeline_handoff.py::test_flow_status_not_degraded_when_db_available`

---

## Applied proposals show as "pending" on the agents dashboard in memory mode

**Symptom:** On the live (memory-mode) deployment, the Learning Loop panel / `GET /dashboard/learning/loop` reported every proposal as `applied=false` even after ProposalApplier had acted on it and changed `signal_weight_scale` / paused trading. The DB-mode path showed the correct `applied`/`applied_at`.

**Root cause:** `get_learning_loop_payload()`'s memory branch maps `_in_memory_proposals(...)`, but that helper never copied the ProposalApplier's `applied` / `applied_at` / `applied_by` / `message` fields off the log payload — so `p.get(FieldName.APPLIED, False)` always fell through to `False`.

**Fix:** `_in_memory_proposals` (`api/services/dashboard/proposals.py`) now carries `FieldName.APPLIED`, `APPLIED_AT`, `APPLIED_BY`, and `MESSAGE` through from the stored log payload, matching the DB path's `recent_proposals` shape.

**Regression test:** `tests/api/test_learning_loop_control_plane.py::test_recent_proposals_carry_applied_flag_in_memory_mode`
