# Troubleshooting — Cognitive Brain (`cognitive/`)

Covers the deterministic, event-stream-driven cognitive trading brain: the single
`EventStream`, the math-only decision engine, observations-only learning, and the
proposal → shadow-backtest → challenger → GitOps-PR evolution loop. See
`cognitive/README.md` for the architecture.

---

## Learning loop starved — Grade/IC/Reflection agents idle with event_count 0

**Symptom:** GradeAgent, ICUpdater, ReflectionAgent and StrategyProposer all show `event_count: 0` and ACTIVE heartbeats, but produce no real grades/IC weights/reflections. Every decision in the feed is `reasoning_summary: "fallback:skip_reasoning"`, `llm_succeeded: false`, and fires a `fallback_trade_blocked` notification (action coerced to `hold`). `orders` stream length 0; `factor_ic_history` / `reflection_outputs` empty.

**Root cause:** The configured Groq model (`llama-3.3-70b-versatile`) was hitting its quota/rate-limit, so the only enabled LLM provider returned a 100% error rate (`success_rate: 0.0`, `last_success_timestamp: null`). Every ReasoningAgent call fell back to skip_reasoning → all trades blocked to `hold` → no fills → the grade/IC/reflection learning loop had nothing to consume. The grading agents themselves were healthy; they were starved at the source.

**Fix (three layers):**
1. **Throttle → instruct fallback** — `_groq_completion` (`api/services/llm_router.py`) now calls the capable `GROQ_MODEL` (`llama-3.3-70b-versatile`) first and, on a 429/quota/rate-limit error, transparently retries the same call on `GROQ_FALLBACK_MODEL` (`llama-3.1-8b-instant`) instead of raising. A throttled primary degrades to a lighter model rather than cascading into skip_reasoning. The model that actually served the call is stamped on the decision's `model_used` label so the learning loop's per-model grading stays truthful.
2. **Per-symbol reasoning cooldown** — `REASONING_COOLDOWN_SECONDS` (default 60s, `api/config.py`) gates the ReasoningAgent so repeat signals for the same symbol within the window are dropped (no LLM call, no degraded-fallback decision). This decouples LLM spend from raw signal volume, which is what burned the quota — momentum signals can fire every few seconds per symbol and each previously triggered a full reasoning call + self-critique call.

Two further spend levers (also `api/config.py`):
- `REASONING_DEDUP_PRICE_PCT` (default 0.05) — skip the LLM when a fresh signal's side matches the last-reasoned one and its price is within this percent (materially identical → no new information). Complements the cooldown for slow-but-repetitive signals.
- `REASONING_SELF_CRITIQUE_ENABLED` (default **False**) — the ReAct self-critique is a *second* LLM call on high-confidence buy/sells; disabled by default to halve actionable-decision spend. Re-enable when provider budget allows.

If `GROQ_MODEL` is pinned via an env var in the deployment, update it (and `GROQ_FALLBACK_MODEL`) there too. Diagnose with `get_llm_health` (per-provider success/error rate) before assuming a grading-agent bug.

**Regression tests:** `tests/core/test_llm_router_rate_limit.py::test_groq_falls_back_to_instruct_when_primary_throttled` (+ healthy / non-rate-limit cases); `tests/agents/test_reasoning_agent.py::test_per_symbol_cooldown_skips_repeat_llm_call` (+ per-symbol scoping).

---

## Tools were tracked but never graded by outcome (alpha frozen at the prior)

**Symptom:** `suggest_tool_changes()` could "disable negative-alpha tools", but in practice no tool's `alpha_score` ever moved off its seeded prior, so the negative-alpha branch never fired and the attribution panel showed priors, not learned value.

**Root cause:** `ToolRegistry.record_call` only updates `alpha_score` when passed `realized_pnl`, and the **only** caller (`ReasoningAgent._record_tool`) runs at *decision* time — before the outcome is known — so it never passed `realized_pnl`. Nothing connected a closed trade's PnL back to the tools that informed the decision. The tool-grading loop was wired up to the registry but never closed.

**Fix:** GradeAgent now consumes `STREAM_DECISIONS` purely to cache `trace_id → tool names` (bounded LRU, `_remember_decision_tools`). When the matching trade closes on `STREAM_TRADE_COMPLETED` / `STREAM_TRADE_PERFORMANCE`, `_attribute_pnl_to_tools` folds the realized PnL into each of those tools' alpha via `record_call(..., realized_pnl=pnl)` and pops the trace so the paired events attribute exactly once. Tool alpha is now outcome-driven, which makes the tool-governance proposal (above) act on real signal. Full closed loop: signal → reasoning (records tools) → decision (`tools_used`) → execution → trade close (PnL) → GradeAgent attributes PnL to tools → `suggest_tool_changes` → tool-governance proposal → operator/ProposalApplier.

**Regression tests:** `tests/agents/test_grade_agent.py::test_trade_pnl_attributed_to_decision_tools` (+ unknown-trace no-op).

---

## Tool governance produced advice but never acted ("it's not automating")

**Symptom:** The ToolRegistry scored each tool's alpha/reliability from live reasoning telemetry and `suggest_tool_changes()` produced disable/review/prioritize advice — but the only consumer was the passive `GET /dashboard/tools` panel. `disable_dead_tools()` was never called anywhere, so the governance loop never closed.

**Root cause:** No agent turned tool suggestions into proposals or actions; the advice just sat in a panel.

**Fix:** `GradeAgent._emit_tool_governance()` (`api/services/agents/pipeline_agents.py`) now runs every grade cycle, publishing actionable tool suggestions (disable / review) as a single `ProposalType.TOOL_GOVERNANCE` approval-gated proposal on `STREAM_PROPOSALS` + an INFO notification. Edge-triggered on the suggestion set so an unchanged set is not re-proposed every cycle. The operator stays in the loop (human approval), and the full suggestion list (incl. the `prioritize` hint) rides along in the proposal content.

**Regression tests:** `tests/agents/test_grade_agent.py::test_tool_governance_emits_proposal_for_actionable_suggestions` (+ informational-only no-op + edge-trigger cases).

---

## Profitable short graded as wrong-direction

**Symptom:** A short position that made money received an `F` direction grade.

**Root cause:** `direction_component` compared `sign(decision_score) == sign(realized_pnl_pct)`. A short has a negative decision score but a *positive* P&L when it is right, so the signs never matched and correct shorts were graded as wrong-direction.

**Fix:** Direction now means "did the directional bet pay off" — `realized_pnl_pct > 0` is correct regardless of side — scaled by move magnitude and conviction (`cognitive/grading.py::direction_component`).

**Regression test:** `tests/core/test_cognitive_grading.py::test_trade_grade_is_multidimensional_not_just_pnl`

---

## Evolution produced no proposal despite a clear edge

**Symptom:** `loop.evolve()` returned `None` even though an agent looked strongly predictive.

**Root cause:** The `LearningEngine` only emits an observation once a signal has `samples >= min_samples` (default 30). With fewer closed trades the importance metadata is statistical noise, so no observation — and therefore no proposal — is produced. This is intended (non-RL, evidence-gated), but is easy to mistake for a bug when testing with a short trajectory.

**Fix:** Feed ≥ `min_samples` closed trades before expecting an observation/proposal; this is by design, not a defect.

**Regression test:** `tests/integration/test_cognitive_loop.py::test_evolve_produces_a_typed_proposal_with_backtest_evidence`

---

## Approved-looking proposal still rejected by the challenger

**Symptom:** A proposal with a positive out-of-sample PnL delta was still rejected.

**Root cause:** The challenger requires ALL guardrails to pass, not just PnL: enough learning samples AND enough backtest trades in BOTH windows, no overfit (in-sample-only improvement), drawdown within tolerance, and attribution consistency. A small out-of-sample trade count trips `statistical_sanity=False` and rejects — correctly preventing evolution on noise.

**Fix:** Expected behaviour. To see an approval, ensure the out-of-sample window yields ≥ `MIN_TRADES` trades on both baseline and candidate.

**Regression test:** `tests/core/test_cognitive_evolution.py::test_challenger_rejects_small_sample_and_bad_attribution`

---

## `cognitive_config.json` change had no effect

**Symptom:** Editing `config/cognitive_config.json` did not change behaviour, or reverted to defaults.

**Root cause:** Config is validated against safe bounds at load (`cognitive/config.py::load_config`). A malformed file, an out-of-bounds value, or `sell_threshold >= buy_threshold` makes the loader fall back to `DEFAULT_CONFIG` rather than apply something unsafe (data-not-code safety, mirroring `api/services/param_overrides`).

**Fix:** Keep values within the documented bounds; the loader silently uses defaults on any validation failure by design. Validate with `validate_config_dict()`.

**Regression test:** `tests/core/test_cognitive_core.py::test_load_config_falls_back_on_missing_or_bad`

---

## News-weight proposals always showed zero backtest impact

**Symptom:** A proposal to change `weights.news` produced a ≈0 backtest delta and was always rejected, even when the News Agent looked predictive live.

**Root cause:** `evolve()` ran the backtest with no sentiment series, so the News Agent stayed neutral and the `news` feature was constant 0 throughout the backtest — multiplying a changed news weight by 0 changes nothing.

**Fix:** The backtest gate accepts a per-bar `news` series; `evolve(..., news=...)` threads it through `evaluate_proposal` and `walk_forward` (`cognitive/loop.py`, `cognitive/backtest_gate.py`), and the demo feeds a deterministic momentum-correlated sentiment series.

**Regression test:** `tests/core/test_cognitive_hardening.py::test_news_weight_is_inert_without_sentiment_but_active_with_it`

---

## A good proposal keeps getting re-proposed / the queue fills with near-duplicates

**Symptom:** The ProposalAgent re-proposes the same change repeatedly, or floods the queue.

**Root cause:** Nothing throttled generation. Now `governance.ProposalGovernor` gates admission, but its brakes can look like "lost" proposals if you don't know they fired.

**Fix:** Proposals are admitted only within a per-window quota, exact duplicates (same target + rounded value) are dropped, and a rejected target is benched for a cooldown. Blocked proposals appear in the queue with `ProposalStatus.BLOCKED` and the reason in `verdict.blocked`; counts are in `snapshot()["evolution"]["governor"]`.

**Regression test:** `tests/core/test_cognitive_hardening.py::test_governor_quota_dedup_and_cooldown`
