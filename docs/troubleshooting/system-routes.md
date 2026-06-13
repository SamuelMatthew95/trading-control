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

---

## Stream-lag telemetry warned `no_active_consumers` on an empty stream

**Symptom:** `get_stream_lag` (MCP telemetry / observability) reported
`health: "warning"`, `reason: "no_active_consumers"` for the `orders` stream,
which has length 0 and is never written in the live pipeline (ExecutionEngine
writes the `orders` *table* + publishes `executions`). A perpetual warning on a
dormant stream is noise that masks real consumer-lag signals.

**Root cause:** `api/mcp/read_tools.py::get_stream_lag_data` flagged any
required-consumer stream with zero consumers, regardless of whether the stream
held any messages. An empty stream has nothing to consume, so a missing consumer
is not a fault.

**Fix:** Added the pure predicate `_flags_missing_consumer(stream_name, stream_length)`
— it only warns when the stream is in `STREAMS_REQUIRING_ACTIVE_CONSUMERS` **and**
`stream_length > 0`. Both call sites (no-group and zero-consumer-group) use it, so
genuine backlogs on non-empty required streams still warn. Dashboard behavior is
unchanged (the `/dashboard/stream-lag` route returns `{}` in memory mode anyway).

**Regression test:** `tests/api/test_stream_lag_consumers.py::test_empty_required_stream_does_not_warn`, `tests/api/test_stream_lag_consumers.py::test_required_stream_with_backlog_warns`

## /analyze 500'd on every call; feedback/performance routes were unregistered

**Symptom:** `POST /analyze` returned HTTP 500 ("Trading service not initialized")
on every request. The `/memory/*`, `/feedback/*`, `/insights`, `/api/statistics`
and `/api/performance` surfaces were missing entirely, and there were no live
`/api/positions` or `/api/pnl` REST endpoints.

**Root cause:** `api/main_state.set_services` was never called at startup, so
`get_trading_service()` raised `RuntimeError`. `feedback.py` / `performance.py`
imported services (`FeedbackService`, `LearningService`) and getters that did
not exist, so the routers could not be imported or registered.

**Fix:** `api/main_state.py` is now a focused route-facing registry holding only
the services REST routes resolve through it — TradingService (wrapping a
`MultiAgentOrchestrator`), FeedbackService, LearningService, PaperBroker — with
never-raising getters that fall back to degraded stubs. Other shared singletons
keep their canonical homes (runtime store → `api.runtime_state`; live agents →
`app.state.agents` via `api.dependencies`), so there is no parallel registry to
drift. `api/startup.py` `_wire_shared_services()` calls `set_services()` once
during the lifespan and publishes the live ReasoningAgent on
`app.state.reasoning_agent` so `api.dependencies.get_reasoning_agent` resolves it
instead of 503-ing. Added `api/services/feedback_service.py` +
`api/services/learning_service.py` (in-memory stubs) and `api/routes/positions.py`
(`/positions` + `/pnl`, PaperBroker-sourced). All three routers are registered in
`api/main.py`.

**Regression test:** `tests/api/test_positions_pnl_routes.py`,
`tests/api/test_feedback_performance_routes.py`,
`tests/api/test_analyze_routes.py::test_analyze_valid_request_returns_200`

## Redis "Too many connections" bursts across unrelated endpoints

**Symptom:** Simultaneous `ConnectionError: Too many connections` warnings from
endpoints that have nothing to do with each other — `positions_broker_read_failed`
(`/positions`, `/pnl`), `redis_store_decision_stats_failed` (`/decisions`),
`redis_store_notification_list_failed` (`/notifications`) — all at the same
instant on a dashboard refresh. The traceback ends in redis-py
`ConnectionPool.get_connection`, **not** at the Redis server.

**Root cause:** Two compounding issues. (1) The shared pool was a plain
`redis.asyncio.ConnectionPool` (`max_connections=20`), which raises
`ConnectionError("Too many connections")` *immediately, client-side*, when every
connection is checked out — it is not a Redis server limit. (2) The web process
runs background blocking reads (`xread` / `xreadgroup`) that each hold a pooled
connection for their block window, and `/positions` + `/pnl` each issued one
`GET` per supported symbol (8 sequential round trips apiece). A dashboard refresh
firing many endpoints at once drained the remaining connections and the pool
raised instead of waiting.

**Fix:** (1) `api/redis_client.py` builds a `BlockingConnectionPool` via
`_build_pool()` — on exhaustion a caller WAITS up to
`settings.REDIS_POOL_TIMEOUT_SECONDS` (5s) for a freed connection instead of
raising; the cap stays at `REDIS_MAX_CONNECTIONS` so the Redis plan's client
limit is never exceeded. (2) `PaperBroker.get_positions()` batches all symbols
into one `MGET`; `api/routes/positions.py::_refresh_mirror_from_broker` uses it,
cutting 8 round trips per request to 1.

**Regression test:**
`tests/core/test_redis_client.py::test_build_pool_returns_blocking_pool`,
`tests/agents/test_paper_broker.py::test_get_positions_batches_into_single_mget`

## Redis pool exhaustion from always-on blocking consumers (`No connection available`)

**Symptom:** Intermittent `warning` logs `Redis connection error during consume`
(`api/events/bus.py`) whose traceback is `ConnectionError: No connection
available.` caused by a `TimeoutError` from
`BlockingConnectionPool.get_connection`, with queued waiters (`waiters:5` /
`waiters:3`) on the pool lock — across unrelated streams/consumers
(`market_events`/`signal-agent`, `decisions`/`execution-engine`) at roughly the
same instants. The trace ends in redis-py's pool `get_connection`, **not** at
the Redis server, and `consume()` swallows it (returns `[]`), so agents look
sluggish/noisy rather than crashing.

**Root cause:** Steady-state pool under-sizing. The whole process shares ONE
`BlockingConnectionPool` capped at `REDIS_MAX_CONNECTIONS=20`, but it runs **~14
always-on blocking stream-reader loops** that each hold a pooled connection
~continuously (`XREADGROUP`/`XREAD BLOCK 100ms`, then immediately re-acquire): 9
pipeline agents + 3 challenger agents + the `EventPipeline` broadcast consumer +
the WebSocket broadcaster `xread` loop. That left only ~6 connections for all
request/response traffic — REST handlers (a dashboard refresh fires ~8–10
concurrently, several doing multiple sequential GETs), per-agent heartbeats, the
price poller's per-symbol GETs, RiskGuardian/gauge-poller scans,
kill-switch/order-lock/IC-weight reads, DLQ ops. A refresh burst pushed demand
over the free slots; because the 14 loops instantly re-grab any freed
connection, request/response callers queued on the pool condition and starved
past `REDIS_POOL_TIMEOUT_SECONDS` (5s). The cap predated the fleet growing to 14
permanent blocking consumers.

**Fix:** `api/config.py` — `REDIS_MAX_CONNECTIONS` default raised 20 → 50, sizing
the pool to *(worst-case always-on blocking loops) + refresh-burst headroom*.
Single gunicorn worker (`-w 1`) means this is the process-wide ceiling; Render
Key Value plan client limits are free=50 / starter=250 (we run starter — verify
in the dashboard before plan changes), so 50 leaves ample margin. Env-overridable
(`REDIS_MAX_CONNECTIONS`) for an immediate restart-only mitigation without a
deploy.

**Prevention (so this cannot silently recur):**
1. *Derived guardrail* — the regression test below constructs the real boot
   fleet via `api/startup.py::_build_agents()` with fakeredis, adds the
   runtime-spawnable challenger capacity (`MAX_CONCURRENT_CHALLENGERS`) and the
   two infra loops (EventPipeline + WebSocket broadcaster), and fails CI when
   `REDIS_MAX_CONNECTIONS` drops below that worst case + 15 request-burst
   headroom. Adding an agent or strategy automatically tightens the assertion —
   no hardcoded fleet count to forget to update. (At the old cap of 20 this
   test fails; at 50 it passes.)
2. *Observability* — `GET /health` now returns a `redis_pool` block
   (`max_connections` / `in_use_connections` / `idle_connections` /
   `saturated`) from `api/redis_client.py::redis_pool_stats()`. The counters
   are pure in-process (zero Redis I/O), so they remain readable precisely when
   the pool is wedged and every actual Redis command is stalling.
   `in_use == max` is the starvation signature.
3. *Always-loaded memory rule* — `.claude/rules/memory-storage.md` → "Redis
   Connection Pool Sizing (HARD INVARIANT)" documents that every new always-on
   consumer adds one permanent connection of demand.

**Regression test:**
`tests/core/test_redis_client.py::test_max_connections_covers_worst_case_always_on_consumers`,
`tests/core/test_redis_client.py::test_redis_pool_stats_reports_fresh_pool`,
`tests/api/test_health_redis_pool.py::test_health_includes_redis_pool_stats`

## Memory mode paints never-started agents "Live"

**Symptom:** In memory mode (`USE_MEMORY_MODE=true`, no Postgres) the Agent
Status table and pipeline cards show agents as **Live** that never actually ran
(e.g. IC Updater, Reflection, Strategy Proposer), so the dashboard looks busier
than the system really is.

**Root cause:** `InMemoryStore.dashboard_fallback_snapshot()` built each
`agent_statuses` row with `last_seen = data.get(LAST_SEEN, now)`. Agents seeded
from `DEFAULT_AGENTS` that never wrote a heartbeat have no `last_seen`, so they
got stamped with the *current* time. The frontend then computed an age of ~0s
and mapped them to "Live".

**Fix:** `InMemoryStore._agent_status_row` (`api/in_memory_store.py`) emits a
sentinel `last_seen=0` / `seconds_ago=-1` for agents with no recorded heartbeat
instead of fabricating `now`, so the UI ages them out to Idle/offline. Real
heartbeats keep their true timestamp.

**Regression test:** `tests/core/test_in_memory_store.py::test_seeded_agents_never_appear_live_without_heartbeat`

## Idle agents earned a fake grade for just being alive

**Symptom:** Agent Scorecards showed agents with **0 events** holding a grade of
"B" / "TRUSTED" (always exactly 72.7%), and seeded agents could even read as
PROMOTED — grading agents that had done no measurable work.

**Root cause:** `agent_performance._grade_agent` graded on any available
dimension, and `_throughput_dimension` counted throughput as "available" even at
0 events. A heartbeating-but-idle agent therefore scored
`liveness / (liveness + throughput) = 0.40 / 0.55 = 72.7%`.

**Fix:** `_throughput_dimension` is unavailable at 0 events, and `_grade_agent`
requires at least one *work* dimension (success / throughput / latency) before
assigning a grade — otherwise the agent is UNRATED. Liveness alone never earns a
letter.

**Regression test:** `tests/api/test_agent_performance.py::test_alive_but_idle_agent_is_unrated_not_graded`

## /health/logs ran SQL in memory mode + both SSE log streams pinned a DB connection

**Symptom:** With no Postgres, `GET /health/logs` immediately emitted an SSE
`error` event (it tried to query `agent_logs`) instead of degrading like
`/system/logs`. Separately, every connected SSE client on either endpoint held
one extra DB pool connection for the stream's entire lifetime.

**Root cause:** `/system/logs` and `/health/logs` each carried their own copy
of the same ~110-line SSE generator; only the `/system` copy had a memory-mode
guard, and in both copies the `while True` poll loop sat *inside* the initial
query's `async with _make_session()` block, so the first session was never
released.

**Fix:** Both generators consolidated into
`api/services/agent_log_stream.py` (`agent_log_stream_response` +
`memory_mode_log_stream_response`). The initial batch runs in its own
short-lived session that closes before the poll loop starts, and both routes
short-circuit to the one-frame memory response when `is_db_available()` is
False. Output shape per route is unchanged (`timestamp` vs `created_at` key,
trace_id only on `/health/logs`).

**Regression test:** `tests/core/test_agent_log_stream.py::test_initial_session_closed_before_first_frame_is_yielded`

## Deploy crash-loop: startup barrier dies on `ConnectionError: No connection available.`

**Symptom:** A Render deploy fails with the gunicorn worker exiting during
startup (`Worker failed to boot`, exit code 3) and the service crash-loops.
The `startup_failed` log shows `redis.exceptions.ConnectionError: No
connection available.` raised from `ensure_all_streams_ready` →
`create_groups` → `XGROUP CREATE`, exactly `REDIS_POOL_TIMEOUT_SECONDS` (5s)
after the barrier started — even though `redis_connected` and
`tool_telemetry_hydrated` succeeded seconds earlier on the same pool.

**Root cause:** The streams startup barrier ran late in the lifespan — after
`start_gauge_poller()` (whose background Redis reads begin immediately) and
`_probe_lmstudio()` (a 10s `asyncio.wait_for` whose cancellation fires right
before the barrier) — so its first `XGROUP CREATE` could time out waiting on
the shared `BlockingConnectionPool` while it was contended. Unlike Postgres
init (`_init_persistence`, retried with backoff), the barrier was single-shot:
one transient Redis hiccup aborted the whole lifespan and failed the deploy.

**Fix:** `api/startup.py` — the barrier now (1) runs immediately after
`_init_redis()`, before any background task can touch the connection pool,
and (2) is wrapped in `_ensure_streams_with_retry()` (backoff 2/4/8s on
`ConnectionError`/`TimeoutError`, zero delay on the happy path, re-raising
after the final attempt — the system cannot run without its streams, so it
still fails closed on a real Redis outage). Additionally `_probe_lmstudio()`
moved off the boot-critical path to a background task
(`app.state.lmstudio_probe_task`): LM Studio is optional and informational,
so an absent/slow local-inference host can no longer delay boot by 10s or
interfere with startup at all.

**Regression test:** `tests/core/test_startup_streams_barrier.py`
