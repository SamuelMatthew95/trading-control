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
- New bounded constant `RISK_ON_BUY_THRESHOLD_DELTA = 0.10` (`api/constants.py`).
- New `regime_risk.is_risk_on()` + `regime_risk.buy_threshold(regime, default, *,
  enabled)` — the **exact mirror of the risk-off long-gate raises**. Where a
  bearish regime RAISES the bar a new long must clear (`min_confidence` /
  `execution_threshold`), a confirmed bullish regime LOWERS the BUY score cut by
  the delta (floored at 0.0). It eases ONLY when the flag is on AND the regime is
  explicitly risk-on; risk-off / neutral / unknown / missing regimes return the
  default unchanged, so a lost regime read can never ease the bar.
- `decide_policy()` resolves the eased cut through that helper and uses it for the
  BUY branch only. The reported `score` and the SELL cut (`params.sell_threshold`)
  are untouched; the eased cut is surfaced in `risk_factors` for audit.

**Design note — why a BUY-cut easing, not a score lean.** The first pass added the
delta to the blended *score*, which shifts the buy AND sell cuts symmetrically — a
marginal bearish signal (score −0.18) would be pulled to −0.08 → HOLD, i.e. a
risk-on regime could *suppress a de-risking SELL*. That brushes against the
constitution's "exits are never blocked by an entry-side gate". Moving the easing
to the BUY threshold only makes it provably entry-side: the SELL cut, the reported
score, and every RiskGuardian exit (stop / take-profit / trailing / daily-loss)
are untouched, so easing can never block a sell. This also keeps `regime_risk`
honest — it is the mirror of the existing risk-off long-gate raises, not a new
risk loosening (the module docstring carves out this single, entry-side, flag-
gated exception explicitly).

Invariants preserved: default-neutral (flag OFF → byte-for-byte the old decision);
strictly entry-side (never suppresses a sell or any exit); never bypasses the
`min_confidence` floor; never weakens the risk-off entry gate. To enable it later,
the bar is ≥20 trades in the named regime WITH a `ReplayHarness` verdict (win rate
/ PnL / Sharpe / FPR) attached.

**Regression test:**
`tests/core/test_decision_policy.py::test_regime_weighting_enabled_never_suppresses_a_sell_in_risk_on`,
`tests/core/test_decision_policy.py::test_regime_weighting_default_off_does_not_change_behaviour`,
`tests/core/test_decision_policy.py::test_regime_weighting_does_not_loosen_risk_off_long_gate`,
`tests/core/test_regime_risk.py::test_buy_threshold_eases_only_in_risk_on_when_enabled`
