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

---

## Signal confidence too low → good trades gated, positions undersized (issue #324)

**Symptom:** The learning loop filed a recurring `regime_adjustment` proposal —
"The model's signal confidence is too low, resulting in suboptimal trades"
(regime `losing`). Genuinely strong momentum moves were being graded with the
same confidence as borderline ones.

**Root cause:** `classify_signal` quantized every signal into three flat tiers —
LOW `0.30`, MOMENTUM `0.55`, STRONG `0.80`. A move at `z = 2.4σ` (nearly STRONG)
scored exactly `0.55`, identical to a borderline `z = 1.5σ` move. Confidence
carries `0.50` of the weighted execution-gate score and scales the Kelly
position size, so this floored confidence (a) lost near-STRONG trades that
scored just under `EXECUTION_DECISION_THRESHOLD` and (b) sized every momentum
trade as if it were borderline.

**Fix:** Graduated confidence WITHIN each tradeable tier. The tier thresholds
still decide the categorical call (signal_type / strength / buy-sell-hold), but
`score` now interpolates from the tier floor toward the next tier's floor by how
deep the move sits in its band (`_graduate_score`): MOMENTUM ramps `55 → 80`
across `[MOMENTUM_SIGMA, STRONG_MOMENTUM_SIGMA]`, STRONG ramps `80 → 95` across
`[STRONG_MOMENTUM_SIGMA, STRONG_MOMENTUM_SIGMA_CEIL]` (clamped). Tier boundaries
are exact — at a boundary the graduated score equals the old flat floor — so
**no buy/sell/hold decision changes**; only the confidence magnitude above a
boundary rises. LOW keeps its flat `0.30` (noise stays below the gate). The
warmup fixed-`%` path graduates identically (`*_PCT_CEIL`). Position size still
rides the hard `MAX_RISK_PER_TRADE_PCT` Kelly cap, so richer confidence cannot
grow a position past the risk limit.

**Fix location:** `api/services/signal_generator.py` (`_graduate_score`,
`classify_signal`, new `*_SCORE_FLOOR` / `*_SCORE_CEIL` / `*_SIGMA_CEIL` /
`*_PCT_CEIL` knobs).

**Regression tests:**
- `tests/core/test_signal_volatility.py::TestGraduatedConfidence` — boundary
  continuity, monotonic deepening, ceiling saturation, LOW floor unchanged,
  fixed-`%` path parity

**Tuning note:** `MOMENTUM_SIGMA` / `STRONG_MOMENTUM_SIGMA` are the primary knobs
now; the backtest harness measures their effect on real Alpaca history before any
change is promoted.
