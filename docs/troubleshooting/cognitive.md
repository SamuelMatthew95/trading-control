# Troubleshooting — Cognitive Brain (`cognitive/`)

Covers the deterministic, event-stream-driven cognitive trading brain: the single
`EventStream`, the math-only decision engine, observations-only learning, and the
proposal → shadow-backtest → challenger → GitOps-PR evolution loop. See
`cognitive/README.md` for the architecture.

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
