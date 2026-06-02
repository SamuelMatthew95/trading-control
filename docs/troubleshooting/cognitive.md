# Troubleshooting — Cognitive Brain (`cognitive/`)

Covers the deterministic, event-stream-driven cognitive trading brain: the single
`EventStream`, the math-only decision engine, observations-only learning, and the
proposal → shadow-backtest → challenger → GitOps-PR evolution loop. See
`cognitive/README.md` for the architecture.

---

## Learning loop starved — Grade/IC/Reflection agents idle with event_count 0

**Symptom:** GradeAgent, ICUpdater, ReflectionAgent and StrategyProposer all show `event_count: 0` and ACTIVE heartbeats, but produce no real grades/IC weights/reflections. Every decision in the feed is `reasoning_summary: "fallback:skip_reasoning"`, `llm_succeeded: false`, and fires a `fallback_trade_blocked` notification (action coerced to `hold`). `orders` stream length 0; `factor_ic_history` / `reflection_outputs` empty.

**Root cause:** The configured Groq model (`llama-3.3-70b-versatile`) was hitting its quota/rate-limit, so the only enabled LLM provider returned a 100% error rate (`success_rate: 0.0`, `last_success_timestamp: null`). Every ReasoningAgent call fell back to skip_reasoning → all trades blocked to `hold` → no fills → the grade/IC/reflection learning loop had nothing to consume. The grading agents themselves were healthy; they were starved at the source.

**Fix:** Switched the default `GROQ_MODEL` to the higher-throughput instruct model `llama-3.1-8b-instant` (`api/config.py`), which has a much larger rate-limit/quota allowance and is sufficient for a clean JSON trading decision. If `GROQ_MODEL` is pinned via an env var in the deployment, update it there too (or unset it to pick up the new default). Diagnose with `get_llm_health` (per-provider success/error rate) before assuming a grading-agent bug.

**Regression test:** `tests/agents/test_reasoning_agent.py` + `tests/api/test_llm_health.py` (model passthrough + provider health reporting).

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
