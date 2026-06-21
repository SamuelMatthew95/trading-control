# Decision Policy (deterministic data plane)

Covers `api/services/decision_policy.py` — the LLM-free fast path that turns a
signal + perception context into a real, explainable decision — and its
regime-conditional weighting (`api/services/regime_risk.py`).

---

## Regime directional weighting — risk-on BUY-cut easing (proposal #346)

**Symptom:** The learning loop filed a `regime_adjustment` proposal — *"The lack
of recent grades or IC changes available is due to the need for more data and
market activity to generate meaningful insights"* — pointing at
`decision_policy.py` (regime → directional weighting) and asking for a behavioural
change in the bullish regime.

**Change:** The deterministic policy now applies a **risk-on directional
weighting** — the mirror of the existing risk-off long-gate tightening. Where a
risk-off (bearish) regime RAISES the bar a new long must clear (`min_confidence`,
`execution_threshold`), an explicit risk-on (bullish) regime LOWERS the policy's
BUY score cut by `RISK_ON_BUY_THRESHOLD_DELTA` (0.10, floored at 0.0), so a
confirmed bullish tape admits marginal longs (score 0.05–0.15) that would
otherwise HOLD.

- New constant `RISK_ON_BUY_THRESHOLD_DELTA` (`api/constants.py`).
- New `regime_risk.is_risk_on()` + `regime_risk.buy_threshold(regime, default)` —
  eases the cut ONLY in an explicit risk-on regime; risk-off / neutral / unknown /
  missing regimes return the default unchanged, so a lost regime read can never
  ease the bar.
- `decide_policy()` uses the eased cut for the BUY branch only and surfaces
  `risk_on_buy_cut` in `risk_factors` for audit.

This is applied behaviour (not behind a flag): in a risk-on regime the eased cut
is always in effect.

**Design note — why a BUY-cut easing, not a score lean.** The first pass added the
delta to the blended *score*, which shifts the buy AND sell cuts symmetrically — a
marginal bearish signal (score −0.18) would be pulled to −0.08 → HOLD, i.e. a
risk-on regime could *suppress a de-risking SELL*. That violates the constitution's
"exits are never blocked by an entry-side gate". Moving the easing to the BUY
threshold only makes it provably entry-side: the SELL cut (`params.sell_threshold`),
the reported `score`, and every RiskGuardian exit (stop / take-profit / trailing /
daily-loss) are untouched, so easing can never block a sell. This also keeps
`regime_risk` honest — it is the mirror of the existing risk-off long-gate raises,
not a loosening of any risk limit (the module docstring carves out this single,
entry-side exception explicitly).

**Invariants preserved:** strictly entry-side (never suppresses a sell or any
exit); fires only in an explicit risk-on regime (a no-op everywhere else, and a
lost regime read keeps the default cut); never bypasses the `min_confidence`
conviction floor; never weakens the risk-off entry tightening; the eased cut is
floored at 0.0 so it can never buy on any positive score.

> **Provenance note:** the triggering proposal's evidence was a single trade
> (`sample_size: 1`, `backtest: null`, `evidence_sufficient: false`). The change
> was applied by operator direction rather than a backtest verdict. If win rate /
> PnL degrade in risk-on regimes, the first lever is `RISK_ON_BUY_THRESHOLD_DELTA`
> (lower it toward 0 to shrink the easing; 0 disables it entirely).

**Regression test:**
`tests/core/test_decision_policy.py::test_regime_weighting_never_suppresses_a_sell_in_risk_on`,
`tests/core/test_decision_policy.py::test_regime_weighting_admits_marginal_long_in_risk_on`,
`tests/core/test_decision_policy.py::test_regime_weighting_does_not_loosen_risk_off_long_gate`,
`tests/core/test_regime_risk.py::test_buy_threshold_eases_only_in_risk_on`
