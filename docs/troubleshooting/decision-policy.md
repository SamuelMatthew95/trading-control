# Decision Policy (deterministic data plane)

Covers `api/services/decision_policy.py` — the LLM-free fast path that turns a
signal + perception context into a real, explainable decision — and its
regime-conditional weighting (`api/services/regime_risk.py`).

---

## Regime directional weighting shipped OFF on preliminary (n=1) evidence — proposal #346

**Symptom:** The learning loop filed a `regime_adjustment` proposal — *"The lack
of recent grades or IC changes available is due to the need for more data and
market activity to generate meaningful insights"* — pointing at
`decision_policy.py` (regime → directional weighting) and asking for a behavioural
change. Its own evidence block was a single trade (`sample_size: 1`, win rate
"100%", `backtest: null`, `evidence_sufficient: false`) in a bullish regime, with
the recommendation "continue with current strategy".

**Root cause:** Not a defect. The proposal is a low-signal watch-item: one
observation cannot distinguish a real regime effect from ordinary trade variance,
and it does not clear the project's "proposals are backtest-backed" bar
(`CLAUDE.md`). Acting on it as written ("first confirm the pattern holds over more
trades… close it if it does not hold") would be premature.

**Fix:** Built the mechanism but left it inert, so default behaviour is unchanged
and it can be opted into only once the evidence firms up.
- New default-OFF flag `REGIME_DIRECTIONAL_WEIGHTING_ENABLED` (`api/config.py`).
- New bounded constant `RISK_ON_DIRECTIONAL_BIAS = 0.10` (`api/constants.py`).
- New `regime_risk.is_risk_on()` + `regime_risk.directional_bias(regime, default,
  *, enabled)` — the profit-side complement to the existing risk-off tightening.
  It adds the long lean ONLY when the flag is on AND the regime is explicitly
  risk-on; risk-off / neutral / unknown / missing regimes return the default
  unchanged, so a lost regime read can never inject a long bias and the
  capital-preservation tightening path is never touched.
- `decide_policy()` resolves the effective lean through that helper, clamps the
  score back into `[-1, 1]`, and surfaces the lean in `risk_factors` for audit.

Invariants preserved: the change is default-neutral (flag OFF → byte-for-byte the
old decision); the lean is strictly entry-side and never blocks an exit; it can
never bypass the `min_confidence` floor; and it never weakens the risk-off entry
gate. To enable it later, the bar is ≥20 trades in the named regime WITH a
`ReplayHarness` verdict (win rate / PnL / Sharpe / FPR) attached.

**Regression test:**
`tests/core/test_decision_policy.py::test_regime_weighting_default_off_does_not_change_behaviour`,
`tests/core/test_decision_policy.py::test_regime_weighting_does_not_loosen_risk_off_long_gate`,
`tests/core/test_regime_risk.py::test_directional_bias_adds_long_lean_only_in_risk_on_when_enabled`
