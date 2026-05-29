# Backtest Harness

Offline strategy-comparison harness (`backtest/` package), the
`/backtest/compare` route, and the dashboard's Strategy Comparison panel.

---

## Verdict trusts near-zero-trade comparisons and ranks inert strategies as winners

**Symptom:** The Strategy Comparison panel showed three strategies at
`+0.00% / 0 trades / 0.00 Sharpe / 0.0% win` and a fourth at `-0.52% / 9 trades`.
The 0-trade strategies sorted to the *top* (above the one that actually traded),
the verdict read `strong_only behaves identically to baseline_momentum → REJECT`,
and the footer claimed "the live baseline over-trades" while the table showed 0
trades.

**Root cause:** The momentum thresholds (`MOMENTUM_PCT = 1.5`,
`STRONG_MOMENTUM_PCT = 3.0` in `api/services/signal_generator.py`) are single-bar
percent triggers, but the harness feeds 1-minute bars (and live feeds 5-second
deltas, `api/workers/price_poller.py:52`) whose per-bar moves are ~0.01–0.3% —
orders of magnitude below 1.5%. So every magnitude-gated strategy correctly sits
in HOLD and records 0 trades; only the direction-only `confirmed_trend` trades.
The engine was faithful (the threshold is mis-scaled to the bar timeframe), but
three presentation layers turned that into a misleading panel: a 0-trade run was
rendered as a measured `0.00%`, inert strategies were ranked by that `0.00%`
above active ones, and the promote/reject verdict was computed on 0 trades.

**Fix:** (honesty + eligibility only — does **not** change live trading thresholds)
- `backtest/challenger.py` — added a `MIN_TRADES_FOR_VERDICT` (30) eligibility
  gate; when the baseline or candidate has too few trades the verdict is
  `INSUFFICIENT_DATA`, distinct from a real `REJECT`.
- `backtest/engine.py` + `backtest/compare.py` — expose a per-strategy `signals`
  count so a 0-trade strategy is classifiable as inactive-by-calibration vs. a
  silent pipeline failure.
- `api/routes/backtest.py` — rank inert (`signals == 0`) strategies last and
  derive the summary from the numbers instead of a hardcoded "over-trades" claim.
- `frontend/src/components/dashboard/BacktestComparisonPanel.tsx` — render inert
  strategies as `NO SIGNALS` with `—` for return/Sharpe/win, and surface the
  `INSUFFICIENT DATA` verdict.

Re-scaling the signal to the bar timeframe (fixed recalibration vs.
volatility-normalized triggers) is a separate, deliberate trading-behavior
decision and is intentionally out of scope here.

**Regression test:** `tests/integration/test_backtest_flow.py::test_challenger_insufficient_data_on_realistic_low_trade_counts`
