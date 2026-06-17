# Agent Lifecycle Troubleshooting

Covers the agent fleet's start/stop/supervision: which agents run, how crashed
tasks are detected and restarted, and the uniform introspection interface
(`name` / `has_crashed`) the supervisor depends on.

## RiskGuardian was started but never supervised

**Symptom:** The stop-loss / take-profit / daily-loss monitor (`RiskGuardian`)
could die and never be restarted — silently disabling position-level risk
enforcement — with no crash alert on the dashboard. `AgentSupervisor` restarted
every stream agent but not RiskGuardian.

**Root cause:** `AgentSupervisor` monitors only the `_build_agents()` list
(`app.state.agents`). `RiskGuardian` is started separately in `startup.py` and
was never added to that list, so it sat outside the supervision loop. It also
lacked the `name` / `has_crashed` properties the supervisor reads, so it could
not have been appended without raising `AttributeError` mid-health-check (which
would have aborted the whole health tick — see the `MultiStreamAgent` entry in
`tests/core/test_base_consumer_crash.py`).

**Fix:**
- Gave `RiskGuardian` and `AgentSupervisor` the same `name` / `has_crashed`
  introspection interface as the stream agents (`MultiStreamAgent`), so the
  background-task agents are uniform with the supervised fleet.
- Wired `RiskGuardian` into the supervised set:
  `AgentSupervisor(event_bus, [*agents, risk_guardian])` (`api/startup.py`).
- RiskGuardian's `_run()` loop already swallows per-cycle exceptions, so the task
  rarely dies; supervision is the backstop for the case where it does. The
  supervisor still cannot restart *itself* — a watchdog can't restart its own
  task — which is why nothing monitors `AgentSupervisor`.

**Regression test:** `tests/core/test_base_consumer_crash.py::test_startup_wires_risk_guardian_into_supervisor`

## Per-agent trust weighting silently undid Grade-C signal dampening

**Symptom:** With `AGENT_TRUST_WEIGHTING_ENABLED` on, a ReasoningAgent the
learning loop had dampened (Grade-C pushes `signal_weight_scale` as low as 0.05)
regained influence — its effective weight jumped back to ~0.5 — so dampening
stopped working.

**Root cause:** `ReasoningAgent.process` clamped the trust-adjusted scale with
`min(max(weight_scale * trust, AGENT_TRUST_MIN), AGENT_TRUST_MAX)`. Trust is a
*multiplier* (already bounded to [0.5, 1.25]); `max(..., 0.5)` on the product
raised any dampened scale up to the 0.5 floor, overriding the learning loop.

**Fix:** `ReasoningAgent._apply_trust_weighting` caps only the top —
`min(weight_scale * trust, AGENT_TRUST_MAX)` — never floor-raising. Result stays
in (0, AGENT_TRUST_MAX].

**Regression test:** `tests/agents/test_reasoning_agent.py::test_apply_trust_weighting_preserves_dampening_and_caps_top`

## Trading agents were never graded on whether they made money (only liveness)

**Symptom:** The Agent Scorecards graded every agent on operational telemetry
only — liveness, success rate, throughput, latency. A SignalGenerator could read
"A / PROMOTED" while the decisions it fed lost money, because realized PnL was
never part of an agent's grade. (PnL was attributed to *tools*, never to agents.)

**Root cause:** `agent_performance._grade_agent` had no PnL dimension, and there
was no per-agent realized-PnL state to read. `GradeAgent` only folded PnL into
tool alpha.

**Fix (durable, no Postgres):**
- `api/services/agent_pnl_store.py` — a Redis-backed `AgentPnLStore`
  (`agent:pnl:{name}` hash, no TTL) accumulating `trade_count` / `win_count` /
  `total_pnl` per agent. Redis is the only correct home: this record must
  survive restarts/deploys and there is no Postgres; InMemoryStore is wiped on
  restart so is deliberately NOT used.
- `GradeAgent._attribute_pnl_to_agents` records each closed trade's realized PnL
  against every agent in `PNL_GRADED_AGENTS` (Signal / Reasoning / Execution).
- `agent_performance` adds a `Realized PnL` dimension (weight `AGENT_PERF_W_PNL`)
  for those agents, and a **promotion gate**: a trading agent cannot reach
  PROMOTED unless its realized win rate clears `AGENT_PNL_PROMOTION_MIN_WIN_RATE`
  over ≥ `AGENT_PNL_MIN_TRADES` trades — a sustained A on liveness alone no
  longer promotes a money-losing agent.

**No bad-data rule:** below the min-trades sample, or with no store, the PnL
dimension reads "no data" (UNRATED on PnL) — never a fabricated 0%, and the gate
treats unproven as not-promotable rather than guessing.

**Regression tests:**
`tests/agents/test_agent_pnl_store.py`,
`tests/agents/test_grade_agent.py::test_attributes_realized_pnl_to_trading_agents`,
`tests/api/test_agent_performance.py::test_trading_agent_graded_on_realized_pnl`,
`::test_pnl_gate_blocks_promotion_when_losing`

## ReasoningAgent defined _compute_kelly_position_size twice

**Symptom:** No runtime misbehavior — but `ReasoningAgent` carried two
near-identical definitions of `_compute_kelly_position_size` (lines ~487 and
~1313), and only the second ever executed (Python silently lets the later
class-body definition shadow the earlier one).

**Root cause:** A refactor moved the Kelly sizing helper next to the risk
hierarchy but left the original copy behind; nothing flags duplicate method
names in a class body.

**Fix:** Removed the dead first definition; the surviving copy (the one that
was already in effect at runtime) is unchanged, so behavior is identical. An
AST sweep confirmed no other duplicate function/method definitions exist in
`api/`.

**Regression test:** behavior-neutral dead-code removal — covered by the
existing reasoning-agent suite (`tests/agents/test_reasoning_*.py`).

## Grade snapshots recorded without the PnL dimension

**Symptom:** For PnL-graded agents the dashboard's live grade could differ
from the recorded snapshot history (the source of promotion streaks) — an
agent could display "B" while accumulating "A" snapshots, making promotion
unexplainable from the UI.

**Root cause:** `record_grade_snapshots` called `_grade_agent` without
`pnl_stats`, while the live view passes them — two different scores for the
same agent.

**Fix:** `record_grade_snapshots` now collects `_collect_pnl()` and passes
each agent's stats, matching the live view
(`api/services/dashboard/agent_performance.py`).

**Regression test:** covered by `tests/api/test_agent_performance.py`
(snapshot path now exercises the same `_grade_agent` inputs as the live view).

## Stored grade records always said fills_graded=None

**Symptom:** Grade history rows (memory mode and the DB agent_grades fallback)
showed `fills_graded: null` even though every grade cycle runs on a known fill
count.

**Root cause:** GradeAgent put `FILLS_GRADED` at the payload top level, but
`write_grade_to_db` receives only the `METRICS` dict and reads
`metrics.get(FILLS_GRADED)` — as does the DB grade-history fallback reader.

**Fix:** `FILLS_GRADED` is also carried inside `METRICS` at payload
construction (`api/services/agents/grade_agent.py`), healing both persistence
paths with no signature changes.

**Regression test:** `tests/agents/test_grade_agent.py::test_grade_metrics_carry_fills_graded`

## Challenger promotion loop spawned unbounded clones and bloated the live prompt

**Symptom:** /dashboard/agents became an endless wall: 15+ near-identical
"challenger being tested" cards (same strategy, 0/20 fills each), a huge
"challenger shadows" list, and an adaptive directive whose ACTIVE text held
~12 stacked "Promoted strategy 'mean_reversion': …" lines (×10 history
versions) — every reasoning call paid for that bloated prompt.

**Root cause (two unbounded feedback legs):**
1. `ChallengerSpawner.spawn` had no dedup or cap: each auto-applied
   challenger promotion spawned a follow-up candidate of the SAME strategy,
   which accumulated shadow evidence, beat baseline, promoted again, and
   spawned another clone — one new fleet member per cycle.
2. `_bias_directive_toward` appended the promotion advisory with
   exact-string dedup only; advisories embed edge/win-rate numbers, so every
   cycle's line was unique and the directive grew without bound.

**Fix:**
- Spawner enforces one RUNNING challenger per strategy (returns the existing
  descriptor with `status: already_running`) and a hard
  `MAX_CONCURRENT_CHALLENGERS` cap (`status: capacity`) — a retired
  challenger frees its slot (`api/services/challenger_spawner.py`).
- The promotion advisory REPLACES the strategy's previous advisory lines
  (stable `Promoted strategy '<name>':` prefix) instead of stacking — one
  line per strategy, and the rewrite self-heals an already-bloated directive
  on the next promotion (`api/services/agents/proposal_applier.py`).
- UI: prior directive versions and challenger-shadow evidence collapse to
  one-line summaries (expand on demand) so the agents page stays one screen
  (`PromptEvolutionPanel.tsx`, `LearningLoopPanel.tsx`).

**Regression tests:**
`tests/agents/test_challenger_spawner.py` (dedup / cap / slot-free),
`tests/agents/test_proposal_applier.py::test_promotion_advisory_replaces_stale_lines_for_same_strategy`

## Agent scorecards read 100% A+ on partial evidence (grades looked fake)

**Symptom:** Operator: "grades of the agents look random — should be real
grades." Scorecards showed `A+ · 100%` with only `3/5 dims scored` (no
latency, no realized-PnL data), every active agent converged on the same
perfect grade, and "streak 50" promotions piled up — the letter carried no
information.

**Root cause:** The blended score renormalized over whichever dimensions had
data, so missing evidence *raised* the grade instead of capping it; throughput
saturated at only 20 events (anything alive maxed it); the PnL promotion gate
accepted a 50% win rate with no requirement that total PnL be positive.

**Fix:** `_grade_agent` multiplies the blend by **data coverage**
(`available_weight / applicable_weight`) so a 3/5-dims agent caps well below
an A and the card explains "Grade capped at N% by data coverage"
(`api/services/dashboard/agent_performance.py`). Thresholds hardened in
`api/constants.py`: `AGENT_PERF_THROUGHPUT_SATURATION` 20→100,
`AGENT_PROMOTION_STREAK` 3→5, `AGENT_PNL_MIN_TRADES` 10→20,
`AGENT_PNL_PROMOTION_MIN_WIN_RATE` 0.50→0.55, and the PnL gate now also
requires **positive total realized PnL** (`_pnl_clears_promotion_gate`).

**Regression tests:**
`tests/api/test_agent_performance.py::test_partial_evidence_cannot_reach_top_grade`,
`::test_pnl_gate_requires_positive_total_pnl`

## Challenger promotion bar was just "beats baseline"

**Symptom:** Challengers became promotion-eligible while losing money — a
strategy that merely lost *less* than a losing baseline proposed itself for
promotion, and the panel's only requirement readout was a trade counter
(`12/25`).

**Root cause:** `_maybe_propose_shadow_promotion` gated on
`CHALLENGER_MIN_SHADOW_TRADES` + `beats_baseline_shadow` only; the
challenger's own win rate / PnL / Sharpe were displayed but never enforced.

**Fix:** `_promotion_blockers()` (`api/services/agents/challenger_agent.py`)
is the single eligibility bar: ≥ `CHALLENGER_MIN_SHADOW_TRADES` (raised
25→40), win rate ≥ `CHALLENGER_MIN_SHADOW_WIN_RATE` (0.55, new constant),
positive shadow PnL, positive Sharpe, AND beats baseline. The proposal path
requires the list to be empty, and `activity_snapshot()` exposes
`promotion_blockers` + `min_shadow_win_rate` so the dedicated
`/dashboard/challengers` page names exactly what is still unmet.

**Regression tests:**
`tests/agents/test_challenger_agent.py::test_no_promotion_when_own_record_is_weak`,
`::test_snapshot_exposes_promotion_blockers`

## Stop-loss / take-profit / daily-loss never fired in memory mode (Postgres-only reads)

**Symptom:** In a no-Postgres (memory mode) deployment, positions rode losses
far past `STOP_LOSS_PCT` and gains past `TAKE_PROFIT_PCT` with no auto-close,
and a string of losing days never tripped the daily-loss kill switch. The
RiskGuardian heartbeat looked healthy the whole time — every scan "completed".

**Root cause:** `RiskGuardian._check_positions` read open positions ONLY from
the Postgres `positions` table (`except Exception: return` swallowed the dead
DB), and `_check_daily_loss` summed ONLY `trade_performance`. In memory mode
positions exist solely in the PaperBroker's `paper:positions:{symbol}` Redis
keys and closed-trade PnL solely in the `closed_trades:recent` Redis mirror —
so every risk check silently no-opped. Exits only happened if the
ReasoningAgent volunteered an opposite-direction decision.

**Fix:** `api/services/agents/risk_guardian.py` routes its position source on
`is_db_available()`: Postgres rows when up (`_load_db_positions`, cached as
before), otherwise a fresh scan of the broker's Redis keys
(`_load_paper_positions`, normalized to the same row shape — `entry_price` →
`avg_cost`, signed qty → unsigned + side). A failed DB read also falls through
to the Redis scan instead of returning. `_today_realized_pnl()` does the same
for the daily-loss limit and circuit-breaker drawdown: `trade_performance` when
the DB is up, else summing today's closes from `RedisStore.list_closed_trades()`
(capped at 100 — a conservative floor that can only under-count).

**Regression tests:**
`tests/agents/test_risk_guardian.py::test_memory_mode_stop_loss_closes_paper_position`,
`::test_memory_mode_short_position_normalized`,
`::test_memory_mode_daily_loss_uses_closed_trades_mirror`

---

## Daily-loss window used the server's local date in DB mode but UTC in memory mode

**Symptom:** On a non-UTC server, the daily-loss kill switch could trip in memory mode but not DB mode (or vice versa) for the same trades near midnight — the two paths summed different "today" windows.

**Root cause:** `RiskGuardian._today_realized_pnl()` bound `date.today()` (server-local calendar day, pre-existing) into the Postgres query while the memory-mode mirror filter used `datetime.now(timezone.utc).date()`.

**Fix:** The DB query now binds the UTC calendar day, matching the memory path and the UTC timestamps agents stamp on trades (`api/services/agents/risk_guardian.py::_today_realized_pnl`). Both ISO-timestamp parse sites in the guardian were also consolidated into a single `_parse_utc_datetime` helper so format handling can't drift.

**Regression test:** `tests/agents/test_risk_guardian.py::test_db_daily_pnl_query_binds_utc_date`

---

## Learning page "Graded Trade Outcomes" showed NR for every trade in memory mode

**Symptom:** On the deployed dashboard (no Postgres) the Learning page's "Graded Trade Outcomes" table rendered every fill with grade **NR**, blank P&L, and no score — grades never appeared even though the GradeAgent was producing them.

**Root cause:** `GradeAgent._backfill_grade_to_lifecycle()` attached the latest agent grade onto the most recent ungraded trade row only in DB mode — it `return`ed immediately when `is_db_available()` was `False`. The deployment runs in memory mode, where the in-memory `store.trade_feed` is the ONLY trade record, so its rows never received a `grade`/`grade_score` and the UI read each as NR.

**Fix:** The back-fill now branches: memory mode merges the grade onto the newest ungraded in-memory fill via `store.upsert_trade_fill()` (keyed on `execution_trace_id`, preserving the original `created_at` so feed ordering doesn't jump), mirroring the existing DB path (`api/services/agents/grade_agent.py::_backfill_grade_to_memory`).

**Regression test:** `tests/agents/test_grade_agent.py::test_backfill_grade_attaches_to_memory_trade_feed`
