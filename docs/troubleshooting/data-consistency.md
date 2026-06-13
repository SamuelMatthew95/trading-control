# Data-Consistency Troubleshooting

The same concepts (PnL, positions, win rate, decisions) used to be computed in
several code paths that drifted out of sync. Each entry below is one such
divergence and the single-source-of-truth that now prevents it.

## Agent event counts and names differed across dashboard panels

**Symptom:** The same agent showed different event counts in different panels
(e.g. Signal Agent: 420 in the Scorecards card vs 138 in the Agent Status
table; Challenger: 414 vs 840) and different names ("IC Updater" on the
Scorecards vs "Information Coefficient Updater" in the Status table).

**Root cause:** No single source of truth for either value. (1) Event count
had three independent sources: the Scorecards read the heartbeat `event_count`
(the canonical tally written by `write_heartbeat()`), while the Agent Status
table and Agent Matrix showed `realtimeCount + persistedCount` — *summing* a
log-derived count and the `agent_instances.event_count` on top of the
heartbeat. (2) Display name had two functions: the backend
`agent_performance._display_name()` (`name.replace("_"," ").title()` →
"Ic Updater") feeding the Scorecards, and the frontend `agentDisplayName()`
(IC special-case) feeding the Status table and pipeline.

**Fix:** One canonical field and one name function across every panel.
`AgentSummary`/`PipelineAgentLike` now carry a single `eventCount`
(`frontend/src/lib/agent-pipeline.ts`), populated in `DashboardView`'s
`realAgents` builder with strict precedence — heartbeat `event_count` wins
outright, falling back to the log count, then `agent_instances.event_count`,
never summed. The Status table, Agent Matrix, and pipeline all read
`agent.eventCount`. Every panel (Scorecards, Status table, Agent Matrix,
pipeline, detail modal) renders names via the frontend `agentDisplayName()`;
the backend `display_name` field is no longer read by the UI.

**Regression test:** `frontend/src/test/helpers/agent-pipeline.test.ts`
(`uses the single canonical event count for a stage (no summing of sources)`)
+ `frontend/src/test/components/AgentStatusTable.test.tsx`.

## Win rate differed between dashboard endpoints

**Symptom:** The Overview P&L card and the paired-P&L view showed different win
rates for the same trades; opening positions dragged the rate down.

**Root cause:** Three memory readers divided winners by `len(orders)` (which
includes opening fills with `pnl=None` and zero-PnL scratches) while a fourth
divided by `winning + losing`. Same data, different denominators.

**Fix:** One canonical definition in `api/services/metrics_calc.py`
(`win_rate = winning / (winning + losing)`, opens and scratches excluded).
`dashboard/pnl.py`, `metrics_aggregator._memory_pnl_metrics` /
`_memory_paired_pnl`, and `in_memory_store.paired_pnl_payload` all use it.

**Regression test:** `tests/core/test_metrics_calc.py::test_three_memory_readers_agree_on_win_rate`

## Active-position count disagreed with the positions list

**Symptom:** The dashboard's "active positions" number could differ from the
number of rows in the open-positions table.

**Root cause:** `open_positions()` required `side in {long, short}` while
`normalized_open_positions()` required only `abs(qty) > 0`, so a `qty>0`
position with a missing side counted in one path but not the other.

**Fix:** Canonical rule `abs(qty) > 0` (side-agnostic — a flat position has
qty 0) via `InMemoryStore.get_active_position_count()` /
`has_active_position()`; `open_positions()` uses the same predicate.

**Regression test:** `tests/core/test_active_position_count.py::test_count_equals_list_length_across_all_read_paths`

## InMemoryStore positions drifted from the broker (and reset on restart)

**Symptom:** Dashboard average cost / unrealized PnL disagreed with the broker
after adding to a position, and positions vanished after a redeploy while the
broker still held them.

**Root cause:** Two independent position ledgers. The execution engine wrote
`InMemoryStore.positions` via `apply_signed_delta` (which preserved the first
entry price on adds) while reject/PnL read the PaperBroker (Redis, weighted
average). Redis persists across restarts; the store does not.

**Fix:** The PaperBroker (Redis `paper:positions`) is the single source of
truth. After every in-memory fill the store mirrors the broker's authoritative
position via `InMemoryStore.mirror_broker_position` (the single
`ExecutionEngine._record_fill_to_store` path), and `startup._hydrate_positions_from_broker`
seeds the mirror on boot so a restart no longer blanks the dashboard.

**Regression test:** `tests/agents/test_execution_position_ssot.py::test_store_position_mirrors_broker_after_add`

## DB-mode position avg cost drifted from the broker on add-to-position

**Symptom:** In DB mode, the Postgres `positions.avg_cost` stayed at the first
entry price after buying more of an existing long, so unrealized PnL on the
dashboard was wrong (same class of bug as the in-memory drift, different layer).

**Root cause:** `upsert_position_db`'s UPDATE branch refreshed side / qty /
prices but never `entry_price` / `avg_cost`, while the PaperBroker recomputes a
weighted average. The DB recomputed the delta independently instead of
mirroring the broker.

**Fix:** `_process_with_db` reads `broker.get_position(symbol)` after the fill
and passes its authoritative entry to `upsert_position_db(avg_cost=...)`, which
now sets `entry_price`/`avg_cost` from it. The legacy/test path (no `avg_cost`)
is unchanged. Same single-source-of-truth principle as the in-memory mirror.

**Regression test:** `tests/agents/test_upsert_position_avg_cost.py::test_update_mirrors_broker_avg_cost_when_provided`

## End-to-end: in-memory mode reaches the dashboard

**Symptom:** Operators doubted whether a BUY→SELL round-trip actually surfaces
on the dashboard in memory mode (the live, Postgres-down path).

**Fix / proof:** `tests/integration/test_in_memory_dashboard_flow.py` drives the
real ExecutionEngine in memory mode (real PaperBroker on fakeredis): a BUY opens
a position the snapshot shows, then a SELL closes it and the PnL payload reports
realized PnL, win rate, the closed trade, and daily-change. A SELL with no
holding leaves the dashboard honestly empty.

**Regression test:** `tests/integration/test_in_memory_dashboard_flow.py::test_buy_then_sell_round_trip_reaches_the_dashboard`

## Closed-trades panel was always empty in production memory mode

**Symptom:** The dashboard's closed-trades list stayed empty even after
round-trips closed, while the paired-PnL view showed realized PnL.

**Root cause:** `store.closed_trades` was written only by the test-only
`apply_decision` replay helper; no production path appended to it, so in live
memory mode it never populated. `paired_pnl_payload` derived closed trades from
`orders` instead, so the two views disagreed.

**Fix:** The canonical fill path (`ExecutionEngine._record_fill_to_store`) now
calls `InMemoryStore.add_closed_trade` on every round-trip close. `apply_decision`
was retired from the production store into `tests/helpers/ledger.py` (test-only).

**Regression test:** `tests/agents/test_execution_position_ssot.py::test_roundtrip_close_sets_order_pnl`

## Proving consistency live — MCP diagnostic tools

When the dashboard looks wrong, run the in-app MCP tools (they reach the live
Redis the standalone script can't): `diagnose_positions` (store vs PaperBroker),
`diagnose_trade_feed` (phantom SELLs), `diagnose_metrics` (canonical win rate),
`diagnose_dashboard_consistency` (one verdict). Each returns `ok` plus the
specific mismatches. Source: `api/mcp/read_tools.py`; tests:
`tests/api/test_mcp_diagnostics.py`.

## Phantom SELLs in the decision feed never produced PnL

**Symptom:** The System page feed showed "SELL AAPL / SELL BTC/USD" but the
dashboard stayed at $0 P&L and 0 positions.

**Root cause:** `ReasoningAgent` published (and recorded to `decisions:recent`)
SELL decisions for symbols with no open position. The `ExecutionEngine`
correctly rejected them (`reject_unmatched_sell`), so they never became orders —
but the advisory feed had already advertised them at decision time.

**Fix:** The agent reads the open-long qty from the PaperBroker (the same source
the engine rejects against) in `_gather_context` and, in `_apply_risk_hierarchy`,
downgrades a SELL for a flat symbol to HOLD tagged
`downgrade_reason=sell_without_open_long`. The feed now only advertises actions
that can execute; the engine reject remains as the backstop. Use
`scripts/diagnose_live_regime.py` to quantify phantom SELLs against live Redis.

**Regression test:** `tests/agents/test_reasoning_position_gate.py::test_sell_with_no_open_long_downgraded_to_hold`

## Frontend now consumes /positions + /pnl directly (broker-truth)

**Symptom:** "Session P&L" only summed closed-trade realized PnL — open-position
unrealized PnL never showed, and positions came solely from the `/dashboard/state`
snapshot.

**Root cause:** `useCodexStore` hydrated positions only from `/dashboard/state`
and had no consumer for the PaperBroker-backed `/positions` / `/pnl` endpoints.

**Fix:** Added `fetchPositions()` (→ `GET /positions`, authoritative merge by
symbol into `positions`) and `fetchPnl()` (→ `GET /pnl`, stored as `pnlSummary`
with the realized/unrealized/total split) to `useCodexStore`. `useRestPoll` calls
both on mount, on every poll, and after a WS reconnect. `TradingView` Session P&L
prefers `pnlSummary.total_pnl` (realized + unrealized) so open-position
mark-to-market is visible, falling back to the DB/trends aggregate then the
trade-feed realized sum.

**Regression test:** `frontend/src/test/store/positions-pnl.test.ts`

## Memory-mode events feed showed the same pipeline event twice

**Symptom:** In memory mode, events from fall-through streams (risk_alerts,
executions, proposals, reflection_outputs, factor_ic_history, notifications)
appeared twice in `event_history` — once rich (with payload), once as a bare
`{id, kind, source, created_at}` row — duplicating rows in every dashboard
panel that reads the events feed.

**Root cause:** `EventPipeline._process_message` appended its generic
events-feed row unconditionally in memory mode, on top of the
`write_event_to_memory` fall-through which had already written the same
`msg_id` into `event_history`.

**Fix:** `write_event_to_memory` (`api/services/persistence_routing.py`) now
returns True when the row landed in the generic `event_history` bucket, and
`_process_message` (`api/services/event_pipeline.py`) skips its own append in
that case. Dedicated-bucket streams (orders, agent_logs, grades, learning
events, trade performance) still get their one generic events-feed row.

**Regression test:** `tests/integration/test_pipeline_flow.py::test_pipeline_memory_fallthrough_stream_lands_once_in_event_history`

## Every closed trade was counted twice by the learning agents

**Symptom:** The durable per-agent PnL store (`agent:pnl:{name}`) showed
`trade_count` / `total_pnl` at exactly 2× reality; trade evaluations appeared
twice in `/learning/trades`; grade / IC / reflection cadences
(`*_EVERY_N_FILLS`) fired at half the configured interval.

**Root cause:** `publish_fill_events` emits the SAME round-trip close to both
`STREAM_TRADE_PERFORMANCE` and `STREAM_TRADE_COMPLETED` (same trace_id, same
realized PnL). GradeAgent, ICUpdater, and ReflectionAgent all subscribe to
both streams and processed the paired events independently.

**Fix:** `PairedCloseDeduper` (`api/services/agents/base.py`) — a bounded LRU
keyed on trace_id, consulted at the top of each agent's `process()`. Only
events carrying both a trace_id and a realized PnL are deduped; opening fills
and trace-less events pass through.

**Regression tests:**
`tests/agents/test_grade_agent.py::test_paired_close_events_graded_once`,
`tests/agents/test_ic_updater.py::test_paired_close_events_counted_once`,
`tests/agents/test_reflection_agent.py::test_paired_close_events_processed_once`

## Opening fills destroyed the decision→tools attribution cache

**Symptom:** Tool alpha (realized-PnL attribution in the ToolRegistry) was only
ever credited on some closes, and `tool_pnl_attribution_failed` warnings
appeared on every position open.

**Root cause:** `GradeAgent._attribute_pnl_to_tools` popped the
trace→tools cache BEFORE validating PnL. An opening fill (pnl None, serialized
to `""` by the bus) consumed the cached tool list, and `""` slipped past the
`is None` check into `float("")`.

**Fix:** Parse/validate the PnL first; only pop the cache when a numeric
realized PnL exists (`api/services/agents/grade_agent.py`).

**Regression test:** `tests/agents/test_grade_agent.py::test_opening_fill_does_not_consume_decision_tool_cache`

## Decisions vanished from the dashboard when the RedisStore was missing

**Symptom:** In memory mode without an installed RedisStore (partial startup,
supervisor restart window), `/dashboard/state` showed zero decisions and
`has_data=false` while the ReasoningAgent was actively deciding.

**Root cause:** `ReasoningAgent._record_decision_to_redis` returned early when
`get_redis_store()` was None — skipping the InMemoryStore ledger writes nested
below the guard, violating the "None degrades, never drops" contract.

**Fix:** The decision/notification payloads are always recorded to the runtime
store in memory mode; the RedisStore push is now the optional mirror
(`api/services/agents/reasoning_agent.py`).

**Regression test:** `tests/agents/test_reasoning_agent.py::test_decision_recorded_in_memory_even_without_redis_store`

## Memory-mode reflections listed twice — one empty

**Symptom:** Every reflection appeared twice in `/dashboard/reflections`; one
copy had empty summary/hypotheses.

**Root cause:** `write_agent_log` dual-writes a reflection in memory mode (a
payload-bearing event_history row + a payload-less agent_logs mirror), and
`_in_memory_reflections` scanned both without dedup.

**Fix:** Collapse to one row per trace_id, preferring the payload-bearing copy
(`api/services/dashboard/learning.py`).

**Regression test:** `tests/core/test_memory_dashboard_reads.py::test_memory_reflections_deduped_to_payload_bearing_row`

## Assorted memory-mode read-path bugs (flow counters, None scores, mixed windows, unbounded dedup set)

**Symptoms / fixes (one commit, same sweep):**
- `/dashboard/flow` claimed 0 orders / 0 trade-lifecycle rows and reported the
  events-feed length as agent logs in memory mode → counts now read
  `len(store.orders)` / `len(store.trade_feed)` / `len(store.agent_logs)`
  (`api/services/dashboard/flow.py`).
- `float(g.get(SCORE) or g.get(SCORE_PCT, 0))` raised TypeError (HTTP 500) on
  grade rows whose score fields exist with value None — `dict.get(key, default)`
  keeps an explicit None → `or 0` coalescing in `api/routes/learning_helpers.py`
  and `api/routes/learning.py`.
- `_performance_trends_from_runtime_store` mixed counts from the paired-PnL
  window (last 100 orders) with sums over ALL orders → averages now computed
  from the same paired window (`api/services/dashboard/trading.py`).
- `InMemoryStore.applied_decision_keys` grew without bound (one key per
  decision ever seen) → bounded by `DECISION_KEY_CAP` with an insertion-order
  deque, same pattern as the pipeline's processed-msg-id cache
  (`api/in_memory_store.py`).

**Regression tests:** `tests/core/test_memory_dashboard_reads.py`,
`tests/core/test_in_memory_store.py::test_decision_dedup_keys_are_bounded`

## Stale duplicate read paths removed (proposals payloads, paired PnL, grade filter)

**Symptoms / fixes (one sweep):**
- `api/services/dashboard/proposals.py` carried near-verbatim dead copies of
  `get_learning_proposals_payload` / `update_proposal_status_payload` missing
  the approve→republish bridge and the events-table fallback — one wrong
  import away from silently regressing approval. Deleted; `prompt_os.py` now
  imports the routed implementation from `dashboard/learning.py`.
- `MetricsAggregator._memory_paired_pnl` re-implemented paired PnL from
  `trade_feed` with the stale fill-time unrealized value, disagreeing with
  every other memory PnL path. Now delegates to the canonical
  `InMemoryStore.paired_pnl_payload()`.
- Memory-mode grade history mixed SignalGenerator's per-signal ACCURACY rows
  into `/dashboard/grades` and the learning-events panel (the DB path filters
  to GradeAgent rows). New single-source filter
  `InMemoryStore.get_overall_grades()` applies the same rule in memory mode.

**Regression test:** `tests/core/test_memory_dashboard_reads.py::test_grade_history_views_exclude_signal_accuracy_rows`

## Header PnL survived restarts but the trades explaining it did not

**Symptom:** After a redeploy the header showed a PnL figure (e.g. -$13.50)
while the dashboard listed only open positions — no closed trades to verify
the number against.

**Root cause:** The header PnL derives from PaperBroker equity, which is
durable in Redis — but closed round-trips were recorded only in the
InMemoryStore, which is wiped on every restart.

**Fix:** The execution engine mirrors each round-trip close to a capped Redis
list (`closed_trades:recent`, `RedisStore.push_closed_trade`), and startup
hydrates `InMemoryStore.closed_trades` back from it
(`api/startup.py::_hydrate_closed_trades_from_redis`) — same pattern as the
broker-position hydration.

**Regression tests:**
`tests/api/test_redis_store.py::test_push_closed_trade_roundtrip_and_cap`,
`::test_startup_hydrates_closed_trades_from_redis`

## Trade Feed blanked after every memory-mode restart (closed trades survived, the feed didn't)

**Symptom:** After a redeploy the Trade Feed panel on /dashboard/trading showed
nothing (`/dashboard/trade-feed` → `count: 0, empty_reason: db_degraded`) even
though the round-trip history was sitting in the Redis `closed_trades:recent`
mirror and the Closed Trades panel could show it.

**Root cause:** Startup hydration only restored `InMemoryStore.closed_trades`;
`trade_feed` started empty and had no rehydration source. The mirror entries
also carried no order/trace ids, and the trade-feed normalizer
(`_normalize_in_memory_trade_row`) drops id-less rows — so they could not have
been projected into the feed even if loaded.

**Fix:** `ExecutionEngine._record_fill_to_store` now mirrors each close with
its identity fields (`order_id`, `execution_trace_id`, `session_id`, `status`),
and `_hydrate_closed_trades_from_redis` projects every mirror entry into a
`trade_feed` row via `_closed_trade_to_feed_row` (`api/startup.py`), giving
legacy id-less entries a deterministic synthetic id so they stay renderable.

**Regression tests:**
`tests/api/test_redis_store.py::test_startup_hydration_rebuilds_trade_feed_rows`,
`tests/integration/test_in_memory_dashboard_flow.py::test_round_trip_close_mirrors_identity_fields_to_redis`
