# Durability Audit — what survives a restart / redeploy (no-Postgres deployment)

**Date:** 2026-06-07
**Context:** This deployment runs with **no Postgres** (`USE_MEMORY_MODE`). Only
**Redis** is durable across process restarts and redeploys (it is an external
managed service). `InMemoryStore` is recreated empty on every start. This
document is the single source of truth for which state survives, which rebuilds,
and which is intentionally transient — so nothing is "silently bad in memory".

## The three durability classes

Every piece of state falls into exactly one class:

| Class | Survives restart? | Meaning |
|---|---|---|
| **DURABLE** | ✅ yes | Lives in Redis (no/long TTL). The source of truth. |
| **ROLLING** | ♻️ rebuilds | In-process window/buffer. Empty on restart, refills from the live Redis stream within one cycle. Degraded-but-self-healing, never authoritative. |
| **TRANSIENT** | ❌ cleared | `InMemoryStore` / UI-only. Expected to reset; with no Postgres this is the only copy of the Postgres-shaped tables, so historical panels reset on restart by design. |

---

## DURABLE — Redis (survives restart & redeploy)

These are the authoritative records. The dashboard reads them, so the
operator-visible "track record" persists across restarts.

| State | Redis key | Owner (write → read) | Notes |
|---|---|---|---|
| Per-agent realized PnL | `agent:pnl:{name}` | GradeAgent → agent_performance | No TTL. Powers PnL grade + promotion gate. |
| Per-agent grade history | `agent:grade_history:{name}` | snapshot task → agent_performance | Drives promotion streak; survives restart so PROMOTED is stable. |
| Adaptive directive + history | `prompt:directive:{node}` (+ `:history:`) | ProposalApplier → ReasoningAgent | Challenger-promotion bias + prompt evolution. Versioned. |
| Notifications (recent) | `notifications:recent` (+ `:read`) | agents → REST | Capped list. |
| Decisions (recent) | `decisions:recent` | ReasoningAgent → REST | Capped list. |
| LLM lifetime/daily metrics | `llm:metrics`, `llm:daily_calls:{date}` | LLMMetricsCollector → `/llm/health` | `/llm/health` merges these durable counts, so the dashboard does NOT show "0 calls" after restart (only the 5-min *window* resets). |
| Tool telemetry (alpha/usage) | `tools:telemetry` | flush task → `hydrate_tool_registry()` at startup | Re-hydrated into the registry on boot. |
| Paper broker state | `paper:cash`, `paper:positions:{symbol}`, `paper:order:{id}` | PaperBroker | Cash/positions reconstructed on restart. |
| Kill switch | `kill_switch:active` (+ `:updated_at`) | RiskGuardian | Safety flag. |
| IC factor weights | `alpha:ic_weights` | ICUpdater | 25h TTL — survives overnight + restarts within the day. |

**UI implication:** agent scorecards (grade, PnL, promotion), tool governance,
prompt-evolution history, LLM lifetime health, positions, and the kill switch
all read durable Redis → **consistent across restarts**.

---

## ROLLING — in-process windows (rebuild from the stream; never authoritative)

These are **intentionally** in-process. They are rolling analytics windows fed
by the Redis streams; on restart they start empty and refill as new events
arrive. They are NOT records of truth, so losing them is degradation, not
corruption. The durable copies above are what the operator's "history" reads.

| State | Where | On restart | Why it's acceptable |
|---|---|---|---|
| `GradeAgent._fills` / `_pnl_buffer` / `_confidence_buffer` / `_eval_buffer` | grade_agent.py | reset → refills over the next N fills | The next grade cycle recomputes from fresh fills; **realized PnL is also written to the durable `agent:pnl` store**, which is what grading persists. |
| `GradeAgent._trace_tools` | grade_agent.py | reset | Only affects tool-alpha attribution for trades whose decision happened *before* the restart — a one-window gap, then normal. |
| `GradeAgent._grade_score_history` / `_self_correction_active` | grade_agent.py | reset | Self-correction re-detects from new grades. |
| `ChallengerAgent._fills` / `_pnl_buffer` / `_grade_history` / `_ticks_observed` / `_recent_shadow_trades` | challenger_agent.py | reset | Challengers are **re-spawned fresh** on startup anyway; a challenger is an ephemeral shadow experiment, not a durable record. |
| `LLMMetricsCollector` 5-min window (`_records`) | llm_metrics.py | reset | Window metric by definition; lifetime/daily come from durable Redis (above). |

**Rule for future code:** if something in this list ever needs to be
authoritative (survive restart), move it to a Redis-backed store (see
`AgentPnLStore` for the pattern) — do **not** rely on the in-process buffer.

---

## TRANSIENT — InMemoryStore (cleared on restart)

`InMemoryStore` mirrors the Postgres tables. **With no Postgres it is the only
copy**, so these reset to empty on restart and rebuild as new events flow:

`agent_runs`, `agent_logs`, `grade_history`, `event_history`, `vector_memory`,
`orders`, `trade_feed`, `trade_evaluations`, `reflections`, `strategies`,
`decisions`, `closed_trades`, `equity_curve`, `notifications`,
`applied_decision_keys`, `rejected_sells`.

**UI implication:** the history-style panels fed *only* by InMemoryStore
(learning-loop trade list, equity curve, event history) **reset to empty on
restart and rebuild over time**. This is expected with no Postgres. The panels
that must stay consistent read the DURABLE Redis sources instead (see above).
Memory-mode `/learning/*` and `/dashboard/state` responses carry
`"mode": "memory"` so the UI can badge this.

---

## Known, accepted trade-offs (explicitly, so they are not "silent")

1. **Historical dashboard panels reset on restart.** Anything sourced only from
   InMemoryStore (equity curve, full event history, learning trade list) starts
   empty after a redeploy. Durable per-agent records (grades, PnL, promotion,
   directive history) do not. *Accepted:* no Postgres ⇒ no long-term row store.

2. **Rolling analytics windows degrade for one cycle after restart.** Grade /
   challenger buffers refill from the stream; the first post-restart grade is
   computed on a smaller window. *Accepted:* self-healing, and realized PnL is
   separately durable.

3. **Memory-mode execution idempotency on crash-before-ack (narrow).** The
   ExecutionEngine's `idempotency_key` dedup is a Postgres `SELECT`, so in memory
   mode it doesn't run. The **primary** guard is the Redis Streams consumer-group
   ack (acked messages are never redelivered) plus the `order_lock` mutex; the
   exposure is only a crash *between* broker fill and ack, in memory mode, within
   the same minute bucket. *Recommendation (not yet implemented):* add a Redis
   `SET NX exec:done:{idempotency_key}` guard in `_process_in_memory` to mirror
   the DB dedup durably. Deferred because the execution path's integration tests
   can't be exercised in the current sandbox; tracked here so it isn't lost.

---

## Test coverage

| Area | Durable-behavior test |
|---|---|
| AgentPnLStore accumulate / degrade-to-None | `tests/agents/test_agent_pnl_store.py` |
| PnL attribution + no-op without store | `tests/agents/test_grade_agent.py::test_attributes_realized_pnl_to_trading_agents`, `::test_pnl_attribution_noop_without_store` |
| PnL dimension + promotion gate | `tests/api/test_agent_performance.py` (graded / below-min / gate win+lose) |
| Tool telemetry hydration on boot | `tests/**/test_tool_telemetry.py` |
| Seeded agents never "Live" without heartbeat | `tests/core/test_in_memory_store.py` |
| Idle agent UNRATED (no fabricated grade) | `tests/api/test_agent_performance.py::test_alive_but_idle_agent_is_unrated_not_graded` |
| Prompt directive durability (Redis) | `tests/agents/test_proposal_applier.py` (challenger-promotion directive) |

**Gaps (documented, not yet covered):** memory-mode execution idempotency on
crash-before-ack (item 3 above); restart-window grade degradation is by design
(no assertion needed).
