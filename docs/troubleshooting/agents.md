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
