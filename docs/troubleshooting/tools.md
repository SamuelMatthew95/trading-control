# Tool Governance — Troubleshooting

Covers the runtime tool registry (`api/services/tool_registry.py`), its telemetry
and PnL attribution, durable persistence, and the `/dashboard/tools` panel.

---

## Tools always read "unused" / alpha looks "random" after a deploy

**Symptom:** Every tool in the Tool Governance panel shows `unused` with an
`α … prior` tag, even though the system has clearly been trading. It looks like
the tools are never exercised or the alpha values are made up.

**Root cause:** TWO compounding things, only one of which was a real bug.
1. *(Not a bug)* In a fresh runtime with no **closed** trades yet, tool alpha is
   genuinely a seeded prior — alpha is attributed from realized PnL only once a
   trade closes (`GradeAgent._attribute_pnl_to_tools`). Decision-time calls
   record latency/usage but intentionally do not move alpha.
2. *(The real bug)* The `ToolRegistry` was a pure in-process singleton with **no
   persistence**. Every redeploy/restart wiped `call_count` / `alpha_score` /
   `latency_ms` back to the seeded catalog, so accumulated usage never survived —
   making a live system permanently look like it had "never used" its tools.

**Fix:**
- Durable telemetry: `ToolRegistry.snapshot()` / `restore()`
  (`api/services/tool_registry.py`) capture/merge the learned fields onto the
  code-defined catalog. `RedisStore.save_tool_telemetry` / `load_tool_telemetry`
  persist them to `tools:telemetry`. `api/services/tool_telemetry.py` loads on
  startup (`hydrate_tool_registry` in the lifespan) and flushes every
  `TOOL_TELEMETRY_FLUSH_INTERVAL_SECONDS` plus once on shutdown, so usage
  survives restarts.
- UI clarity: the panel was rebuilt as a standard aligned table grouped by DAG
  phase, and explicitly explains the seeded-prior state when nothing has been
  exercised yet (`ToolGovernancePanel.tsx`).

**Note:** The wiring itself was already correct — tools ARE recorded in the live
reasoning + execution paths and alpha IS deterministic (no `random` anywhere).
The visible problem was non-persistence + an unclear UI, not fabricated data.

**Regression test:** `tests/api/test_tool_telemetry.py` (flush→restart→hydrate
roundtrip) + `tests/api/test_tool_registry.py` (snapshot/restore) +
`frontend/src/test/components/ToolGovernancePanel.test.tsx`.

## Tool alpha graded only the exit half of every round trip

**Symptom:** Entry-decision tools (the look-ups behind the BUY) never
accumulated realized-PnL alpha — only the SELL decision's tools were credited,
so tool governance judged every tool on half its actual influence.

**Root cause:** The round-trip-close events carry only the CLOSING decision's
trace_id; GradeAgent's trace→tools cache therefore could never resolve the
entry decision at attribution time.

**Fix:** When a BUY order FILLS (`STREAM_EXECUTIONS`), the decision's cached
tools are promoted to a bounded per-symbol entry slot
(`GradeAgent._remember_entry_tools`); on close,
`_attribute_pnl_to_tools` credits BOTH the closing-trace tools and the entry
tools (one credit per tool per trade, both caches popped so a redelivered
close can't double-credit). Gated/rejected decisions never fill, so they can't
pollute attribution.

**Regression tests:**
`tests/agents/test_grade_agent.py::test_entry_decision_tools_credited_on_round_trip_close`,
`::test_gated_decision_never_pollutes_entry_attribution`
