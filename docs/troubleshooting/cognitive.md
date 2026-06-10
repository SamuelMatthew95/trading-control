# Troubleshooting — Cognitive Brain (`cognitive/`)

Covers the deterministic, event-stream-driven cognitive trading brain: the single
`EventStream`, the math-only decision engine, observations-only learning, and the
proposal → shadow-backtest → challenger → GitOps-PR evolution loop. See
`cognitive/README.md` for the architecture.

---

## LLM-down fallback emitted phantom directional trades (fail OPEN)

**Symptom:** When the reasoning LLM was unavailable, the dashboard showed `buy`/`sell`
decisions tagged `fallback:skip_reasoning` — the system *looked* like it wanted to trade
on raw momentum with no reasoning behind it ("random fallback to just buy").

**Root cause:** `LLM_FALLBACK_MODE` defaulted to `skip_reasoning`, whose `_apply_fallback`
branch derives a directional action from signal direction / `pct` momentum. The
ExecutionEngine's `ALLOW_FALLBACK_TRADES=False` guard blocked the *order*, but the
ReasoningAgent still *emitted* a misleading directional decision — failing open at the
cognition layer.

**Fix:** Default `LLM_FALLBACK_MODE = "reject_signal"` (`api/config.py`, mirrored in
`api/constants.py`). Brain-down now emits a transparent `REJECT` (no order, recorded and
visible) instead of a naive momentum buy/sell — capital-preservation-first, the
constitution's top rule. Naive directional (`skip_reasoning`) and last-reflection reuse
(`use_last_reflection`) remain opt-in. Two layers of safety now: cognition emits REJECT,
and the ExecutionEngine still blocks fallback buys.

**Regression test:** `tests/agents/test_reasoning_agent.py::test_fallback_rejects_by_default_no_phantom_trade`
(+ `::test_fallback_directional_is_opt_in_only`).

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

## Auto-PR for parameter changes (GitOps)

**What:** When the learning loop approves a `PARAMETER_CHANGE`, `ProposalApplier`
now opens a real pull request via `GitOpsPublisher` (`api/services/gitops_publisher.py`)
that edits `config/param_overrides.json` — the same bounds-validated overrides
document the GitHub Action path edits, loaded by `api/constants.py` at import — a
**config file, never source code**, version-controlled and human-reviewed.

**Safety:** Acts only when `GITHUB_AUTOPR_ENABLED` is set AND `GITHUB_TOKEN` (in Render)
+ `GITHUB_REPO` are present. Locally / in tests / CI (no token) every call is a dry-run
no-op touching no network. All failures are swallowed — a GitOps hiccup never breaks the
trading loop; the queued `pr_request` artifact remains for the GitHub Action / manual review.

**Regression test:** `tests/api/test_gitops_publisher.py`

## Tool Governance panel shows tools that never seem to be used / alpha looks like fiction

**Symptom:** The Tool Governance panel lists ~13 tools each with an alpha score, but an operator cannot tell which tools the reasoning LLM actually calls — every tool shows a number, so seeded priors are indistinguishable from earned attribution and the panel reads as meaningless.

**Root cause:** Two gaps. (1) The UI rendered `alpha_score`/latency/err but never the `call_count`/`success_count` the registry already tracks, so usage was invisible. (2) `get_stream_confluence_metrics` was registered and shown to the LLM but never recorded as exercised — a "ghost" tool stuck on its seeded prior forever, even though the signal's composite confluence score informs every decision.

**Fix:** `ToolGovernancePanel.tsx` now shows each tool's call ledger (`N× · M ok`) or an explicit `unused` marker, tags a never-called tool's alpha as a `prior` (seed, not earned), and summarises live coverage (`X/Y exercised live`). `ReasoningAgent._build_context` (`reasoning_agent.py`) records `TOOL_STREAM_CONFLUENCE` from the in-hand composite score (gated on its registry enabled flag, like the other perception tools). Execution/optimization-phase tools (`risk_cage`, `vwap_execution`, `bracket_order`, `replay_regression`) legitimately belong to downstream nodes and now read honestly as `unused` at the reasoning node rather than as fake earned alpha.

**Regression test:** `tests/agents/test_reasoning_agent.py::test_process_records_stream_confluence_tool` + `frontend/src/test/components/ToolGovernancePanel.test.tsx`

## Execution / optimization tools sit forever as seeded priors (`unused`)

**Symptom:** After making the reasoning-node tools live, the RISK/EXECUTION/OPTIMIZATION-phase tools (`risk_cage`, `vwap_execution`, `bracket_order`, `replay_regression`) still showed as `unused` in tool governance — the panel only ever reflected perception/memory tools.

**Root cause:** Those tools were registered and grouped by phase but never recorded a call: nothing in the execution engine or promotion gate folded them into the registry. `vwap_execution` also carried a misleading `0.8` alpha prior, so once it *did* go live it would have displayed fake earned edge — execution mechanics have no directional alpha (they run at entry; PnL realizes at exit, with no entry→exit tool threading).

**Fix:** Execution-phase tools are now graded on **telemetry (latency + reliability), not alpha**. `ExecutionEngine._check_pre_execution_gates` is a timing wrapper over `_evaluate_pre_execution_gates` that records `risk_cage` once per evaluated trade; `_build_vwap_plan` records `vwap_execution` when a slicing plan is built; each `broker.place_order` call records `bracket_order` with measured submit latency (`execution_engine.py`). `PromotionGate.evaluate` and `GradeAgent._recent_backtest_evidence` record `replay_regression` when a regression/backtest replay runs (`promotion_gate.py`, `pipeline_agents.py`). All recordings are best-effort (never raise into the trading path). The `vwap_execution` seed alpha is now `0.0` (neutral) so a live mechanics call never shows fake earned edge — the top directional-alpha tool is now the perception confluence metric.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_risk_cage_tool_recorded_on_every_gate_evaluation`, `::test_vwap_tool_recorded_only_when_a_slicing_plan_is_built`, `::test_vwap_execution_tool_seeds_neutral_alpha`, `tests/api/test_promotion_gate.py::test_promotion_gate_records_replay_regression_tool`

## A TOOL_GOVERNANCE proposal is approved but the dead tool never gets disabled

**Symptom:** GradeAgent emits a `TOOL_GOVERNANCE` proposal (e.g. "disable scan_sector_correlation — negative alpha"), it shows on the proposal queue, but approving it does nothing — the tool stays enabled and keeps reaching the reasoning prompt. The worker logs `proposal_skipped_unknown_type`.

**Root cause:** `ProposalApplier._handlers` had no entry for `ProposalType.TOOL_GOVERNANCE`, so the proposal fell through to the `handler is None` branch and was silently dropped. The dead-tool loop never closed through the applier.

**Fix:** Added `_apply_tool_governance` (`proposal_applier.py`) wired into the handler map. It disables every tool a suggestion flagged with `action == "disable"` via the new `ToolRegistry.set_enabled(name, False)` (`tool_registry.py`); `review` suggestions stay advisory. Returns None when nothing changed so no misleading "applied" log fires. The next reasoning prompt drops the disabled tool.

**Regression test:** `tests/agents/test_proposal_applier.py::test_tool_governance_disables_flagged_tools`

## The proposal queue doesn't say where an approved proposal goes (config PR vs issue)

**Symptom:** The proposal table shows the proposal `Type` but not its destination, so an operator can't tell whether approving will open a config pull request, flip a control-plane flag, or file a GitHub issue for human design.

**Fix:** Added `frontend/src/lib/proposal-routing.ts` — a pure map mirroring the backend handler map — and an "On Approve" column in `ProposalsSection.tsx` that badges each row: `Config auto-PR` (parameter_change), `Control plane` (weight/suspension/retirement), `Prompt store` (prompt_evolution), `Tool registry` (tool_governance), `Challenger / issue` (new_agent), `GitHub issue` (code_change / regime_adjustment).

**Regression test:** `frontend/src/test/helpers/proposal-routing.test.ts`

## ~87% of decisions are `fallback:reject_signal` — Groq throttling cascaded into REJECTs

**Symptom:** Live dashboard shows almost every reasoning decision as `action: reject` / `reasoning_summary: "fallback:reject_signal"` / `llm_succeeded: false`. Downstream everything looks idle: no fills, no grades, the learning agents (`IC_UPDATER` / `REFLECTION_AGENT` / `STRATEGY_PROPOSER`) sit at `event_count: 0`, execution tools never run. `GET /llm/health` reports `groq … success_rate 12.5%, rate_limit_count 7`.

**Root cause:** The Groq path (`_groq_completion`) tried the capable model, fell back to the instruct model **once** on a 429, and if that was also throttled it raised immediately. A single transient free-tier rate-limit therefore became a REJECT (the agent fails closed). The Gemini path already had sliding-window limiting + backoff retry; Groq had neither — so on a busy free tier the reasoning LLM failed most calls and starved the whole learning half of the cognition loop.

**Fix:** `api/services/llm_router.py::_groq_completion` now loops `LLM_MAX_RETRIES` times: capable → instruct, and when **both** tiers are rate-limited it sleeps a bounded exponential backoff (`_groq_backoff_delay`, capped at `MAX_BACKOFF_SECONDS`) and retries the pair. Non-rate-limit errors still raise immediately. After retries are exhausted it still raises, so the agent continues to **fail closed (REJECT)** — backoff lifts the success rate, it never fabricates a trade.

**Note (ops):** The underlying cause is free-tier Groq quota. Code resilience reduces transient rejects but cannot create quota — a sustained fix is a working provider/quota (`LLM_PROVIDER` + key, or a paid tier).

**Regression tests:** `tests/core/test_llm_router_rate_limit.py::test_groq_retries_with_backoff_when_both_tiers_throttled`, `::test_groq_raises_after_retries_exhausted_so_agent_fails_closed`
