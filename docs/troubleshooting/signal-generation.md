# Signal Generation Troubleshooting

Live `SignalGenerator` (`api/services/signal_generator.py`) and the
`classify_signal` decision it shares with the `backtest/` harness.

---

## Bot sits idle / "no signals" — fixed-% trigger never fires on tick data

**Symptom:** The dashboard showed challengers stuck at `0/200 fills`, Recent
Decisions at `Buys: 0 / Sells: 0`, an empty learning loop, and the Move
Distribution panel reporting the `1.5%` / `3.0%` triggers at `p100` ("never").
The bot was plugged in but effectively never traded.

**Root cause:** `classify_signal` gated buy/sell on a fixed single-bar move
(`abs(pct) >= MOMENTUM_PCT`, with `MOMENTUM_PCT = 1.5`). Those thresholds were
scaled for coarse bars, but the live feed delivers 5-second deltas / 1-minute
bars whose per-bar moves are ~0.01–0.3% — 100–300x below 1.5%. So virtually
every move classified as LOW/`hold`. (Previously flagged as a deliberate,
out-of-scope decision in [backtest.md](backtest.md); that decision has now been
made.)

**Fix:** Volatility-normalized triggering (`move > k·sigma`). `classify_signal`
now grades a move by its z-score (`|pct| / sigma`) against `MOMENTUM_SIGMA`
(1.5) and `STRONG_MOMENTUM_SIGMA` (2.5), where `sigma` is the rolling stdev of
recent percent-returns from `compute_return_sigma`. This self-calibrates to the
bar timeframe, so the trigger fires sensibly on ticks AND minute bars. The fixed
`*_PCT` thresholds remain as the warmup fallback (until `SIGMA_MIN_SAMPLES`
returns exist) and for callers that pass no `sigma`, which keeps existing
single-tick pipeline tests valid. The live agent (`process()`) and the backtest
`baseline_momentum` both feed the SAME `compute_return_sigma` estimate, so they
never silently diverge. Measured: the realistic 0.1%-vol series that produced 0
trades now produces ~138 trades over 2000 bars.

**Fix location:** `api/services/signal_generator.py` (`compute_return_sigma`,
`classify_signal`, `process()`); `backtest/strategies.py` (parity).

**Regression tests:**
- `tests/core/test_signal_volatility.py` — z-score gating, warmup fallback, and the sigma estimator
- `tests/integration/test_backtest_flow.py::test_volatility_normalized_signal_trades_at_low_absolute_volatility`

**Tuning note:** `MOMENTUM_SIGMA` / `STRONG_MOMENTUM_SIGMA` are the primary knobs
now; the backtest harness measures their effect on real Alpaca history before any
change is promoted.
