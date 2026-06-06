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
