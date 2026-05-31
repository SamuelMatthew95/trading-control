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

---

## Prompt-OS built but the buy/sell LLM never used it (tools, constitution, telemetry all dead)

**Symptom:** The `/dashboard/tools` Tool Governance panel rendered the seeded catalog, but every tool's `call_count` stayed `0` forever and the constitution / node-scoped tool selection had no effect on real decisions. The ReasoningAgent — the LLM that actually decides buy/sell — was emitting decisions with the static `ADAPTIVE_TRADING_SYSTEM_PROMPT`, so the Prompt-OS (constitution + Tool Registry + prompt assembly) was scaffolding wired to nothing.

**Root cause:** `ReasoningAgent._call_llm()` passed `ADAPTIVE_TRADING_SYSTEM_PROMPT` directly to `call_llm_with_system()`. Nothing in the agent imported `build_runtime_prompt`, `get_tool_registry`, or `SYSTEM_CONSTITUTION_PROMPT` — the only callers of those were the read-only route and the tests.

**Fix:** `ReasoningAgent` now assembles its decision system prompt via `_assemble_decision_prompt()` — `SYSTEM_CONSTITUTION_PROMPT` (immutable Layer 1) + ONLY the perception/memory tools the registry deems eligible for the reasoning node (negative-alpha tools filtered by `REASONING_TOOL_MIN_ALPHA`) + a compact regime/portfolio summary + `DECISION_OUTPUT_CONTRACT`. It records real telemetry (`record_call`) for the `get_ic_weights` and `query_similar_trades` tools it exercises, so the panel and dead-tool suggestions reflect live usage. Tool names/flags are shared constants in `api/constants.py` so the registry and the agent can never drift. `record_call`'s `realized_pnl` is now optional so decision-time calls update latency/reliability without dragging the seeded alpha prior to zero. The `/dashboard/tools` response gained a `suggestions` block (`ToolRegistry.suggest_tool_changes()`) — read-only "which tools to keep/drop from the prompt" advice the operator approves — rendered in `ToolGovernancePanel`.

**Operator check:** After a few decisions, `GET /dashboard/tools` shows `call_count > 0` for `get_ic_weights` / `query_similar_trades`, and `suggestions` lists at least the negative-alpha `scan_sector_correlation` disable hint.

**Regression tests:** `tests/agents/test_reasoning_agent.py::test_call_llm_assembles_tool_governed_prompt`, `tests/agents/test_reasoning_agent.py::test_process_records_tool_telemetry`, `tests/api/test_tool_registry.py::test_tools_endpoint_returns_suggestions`

---

## Strategy proposals existed but were unreachable in the UI

**Symptom:** `ProposalsSection` (voteable approve/reject proposals) only rendered under `DashboardView section="proposals"`, but there was no nav entry and no `/dashboard/proposals` page route, so operators could never reach it. Proposals flowed all the way to `/dashboard/state` (DB and memory mode both include `FieldName.PROPOSALS` via `dashboard_fallback_snapshot()`) but had nowhere to surface.

**Root cause:** Missing `frontend/src/app/dashboard/proposals/page.tsx` and a missing `NAV` entry in `frontend/src/app/dashboard/layout.tsx`.

**Fix:** Added the `proposals/page.tsx` route (renders `<DashboardView section="proposals" />`) and a "Proposals" nav link, so the existing data path now has a visible destination.

**Operator check:** `/dashboard/proposals` loads and shows pending proposals with Approve/Reject buttons; empty state reads "No proposals yet — they arrive from the ReflectionAgent".

---

## Learning-events panel shows every grade 2-3x in memory mode

**Symptom:** With `USE_MEMORY_MODE=true` (or Postgres down), the dashboard's learning-events / grade feed shows each grade duplicated two or three times — and the duplicates disagree (one row has the letter grade, another has `grade: null`; scores differ in scale).

**Root cause:** `InMemoryStore.add_grade()` had no dedup, but the same grade reaches `grade_history` up to three times in memory mode: `GradeAgent` calls both `write_agent_log(LogType.GRADE, …)` and `write_grade_to_db(…)` (each routes to `add_grade`), and then the `EventPipeline` re-delivers the same grade from `STREAM_AGENT_GRADES` and calls `add_grade` again (`api/services/persistence_routing.py::write_event_to_memory`).

**Fix:** `add_grade` now dedups by `trace_id` (`api/in_memory_store.py`): a re-delivered grade merges into the first row (existing values win, new fields like `self_correction` fill in) so one enriched grade survives. Challenger grades carry no `trace_id`, so they always append and are never collapsed together.

**Regression test:** `tests/agents/test_in_memory_persistence.py::test_add_grade_dedups_same_trace_id`, `tests/agents/test_in_memory_persistence.py::test_add_grade_without_trace_id_always_appends`

---

## EventPipeline logs `pipeline_persist_skipped` warnings on every grade / proposal / reflection / IC update

**Symptom:** With Postgres up, the logs fill with `pipeline_persist_skipped` warnings for `agent_grades`, `proposals`, `reflection_outputs`, `factor_ic_history`, and `executions` — one per event — even though the system is healthy and the data is in the DB.

**Root cause:** The `EventPipeline` treated its DB persistence as a "secondary safety net" and re-wrote these streams via `SafeWriter`. But the producing agents are the *authoritative* writers (`GradeAgent.write_grade_to_db`, `StrategyProposer.persist_proposal`, `ReflectionAgent.write_agent_log` + `persist_reflection_record`, `ICUpdater`, and `ExecutionEngine` via `order_writer`/`upsert_position_db`/`upsert_trade_lifecycle`), and the stream payloads omit fields the `SafeWriter` validators require (`agent_id`/`agent_run_id`/`grade_type`, `ic_value`, `trace_id`, `insights`, Position `quantity`…). So the pipeline write *always raised* and was swallowed as a warning — pure noise, never a real row.

**Fix:** `api/services/persistence_routing.py` adds `_AGENT_OWNED_DB_STREAMS`; `determine_persist_route` returns `SKIP` for those streams when the DB is up (the agent already wrote the durable row). The pipeline still broadcasts them, and the MEMORY fallback when the DB is down is unchanged, so memory-mode hydration (and challenger grades, which only flow via the stream) is preserved.

**Regression test:** `tests/integration/test_pipeline_flow.py::test_determine_persist_route_skip_for_agent_owned_when_db_available`, `tests/integration/test_pipeline_flow.py::test_determine_persist_route_agent_owned_still_memory_when_db_down`

---

## Open positions show as "degraded" on the memory-mode trade feed

**Symptom:** In memory mode, `GET /dashboard/trade-feed` tagged normal open BUY rows with `degraded_reason: "invalid_numeric_fields_sanitized"` and `sanitized_fields: ["exit_price", "pnl"]`. An open position has no exit price or realized P&L yet, so a perfectly healthy trade looked corrupt.

**Root cause:** The in-memory store sometimes writes the **string** `"None"` (not real `null`) for an open position's `exit_price`/`pnl`. `_normalize_in_memory_trade_row`'s `_pick_num` flagged any field whose raw value was non-`None` but unparseable — which captured the null-like sentinel strings `""`, `"null"`, `"None"` as if they were malformed numbers. NaN/Inf also leaked through `float()` into the JSON.

**Fix:** `api/services/dashboard/trading.py` adds `_is_null_like_numeric()` — null-like sentinels (`None`, `""`, `"null"`, `"none"`, non-finite floats) are treated as legitimately absent and are no longer flagged; only genuinely malformed values (e.g. `"abc"`) trip `degraded_reason`. `_safe_numeric` now also drops NaN/Inf so they never reach the response.

**Regression test:** `tests/api/test_trade_feed_sanitization.py::test_open_position_with_absent_exit_and_pnl_is_not_degraded`, `tests/api/test_trade_feed_sanitization.py::test_trade_feed_drops_non_finite_numeric_values`
