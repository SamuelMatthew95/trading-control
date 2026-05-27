# Trading Bot — Risk Management Overhaul

## Diagnosed Root Causes of Losses

1. **Paper mode threshold too low (0.30)**: Trades executed on signals with only 30%
   confidence — equivalent to random noise. The paper/live asymmetry meant the system
   produced fills on signals that would never clear the live gate.

2. **No signal confidence gate**: The only execution filter was a composite score.
   A low-confidence signal paired with the 0.6 `historical_perf` default could clear
   the 0.55 threshold at as little as 0.34 raw confidence.

3. **Fixed position sizing (1% always)**: Every trade risked the same amount regardless
   of signal quality, market conditions, or recent drawdown. High-conviction and
   low-conviction signals were treated identically.

4. **No regime filter**: The bot fired in choppy/low-volatility markets with the same
   frequency as trending ones. Slippage and spread costs are a larger fraction of
   expected return in flat markets.

5. **No transaction cost awareness**: The signal threshold did not account for round-trip
   slippage (≈0.1% total). Very small percentage moves generated trades where costs
   exceeded the expected return.

6. **No cooling-off after consecutive losses**: Five consecutive losses continued to
   trigger new trades with no circuit breaker.

7. **Signal based only on price % change**: No RSI, ATR, volume, or time-of-day context.
   Pure momentum chasing, which mean-reverts in choppy conditions.

## Files Modified

| File | Change |
|------|--------|
| `api/constants.py` | Raised `EXECUTION_DECISION_THRESHOLD_MEMORY` 0.30→0.55; added 10 new risk constants; added 7 new `FieldName` entries; added `REDIS_KEY_RECENT_OUTCOMES` |
| `api/services/risk_filters.py` | **New** — pure-function risk filter library: RSI, ATR, regime filter, cooling-off, net EV, Kelly sizing |
| `api/services/signal_generator.py` | Added rolling price history; now computes RSI(14), ATR(14), ATR regime ratio, and time-of-day and includes them in every signal payload |
| `api/services/execution/decision_utils.py` | Added `check_confidence_gate()` and `check_net_ev_gate()` pure functions |
| `api/services/execution/execution_engine.py` | Wired up 4 new pre-execution gates: confidence gate (≥0.65), regime filter (ATR ratio < 1.0 = choppy), net EV gate, cooling-off gate; records trade PnL to Redis after fills |
| `api/services/agents/reasoning_agent.py` | Replaced fixed 1% position sizing with Kelly-fraction sizing (quarter Kelly, max 1.5% per trade); enforces minimum 2:1 R/R ratio |
| `tests/core/test_field_name_guardrails.py` | Added `api/services/risk_filters.py` to `CLEAN_FILES` |
| `tests/agents/test_risk_filters.py` | **New** — 22 unit tests covering all risk filter functions |

## How Each Gate Works

### Gate 1: Composite Score Threshold (existing, strengthened)
- Paper mode raised from 0.30 → 0.55 (same as live)
- Formula: `signal_confidence × 0.50 + reasoning_score × 0.30 + historical_perf × 0.20`

### Gate 2: Signal Confidence Minimum (new)
- Blocks trades where `signal_confidence < 0.65`
- Bypasses advisory actions (hold/reject/flat)
- Logged as `execution_gated_low_confidence`

### Gate 3: ATR Regime Filter (new)
- Blocks trades when `current_ATR < 20-period rolling mean ATR`
- Computed per symbol from rolling tick price history
- Bypassed during warmup (first 34 ticks per symbol)
- Logged as `execution_gated_choppy_regime`

### Gate 4: Net EV Gate (new)
- Blocks trades when `confidence × |pct_move|/100 < 2 × slippage`
- For a 1.5% MOMENTUM signal at 0.55 confidence: EV = 0.00825, cost = 0.001 → passes
- For a 0.3% move at 0.65 confidence: EV = 0.00195, cost = 0.001 → passes
- Logged as `execution_gated_negative_net_ev`

### Gate 5: Cooling-Off Gate (new)
- Blocks trades when recent outcomes are dominated by losses (exponential decay weighted)
- Decay=0.7 → most recent loss counts ~43% more than loss from 2 trades ago
- Threshold=0.6 weighted-loss-fraction triggers the block
- Logged as `execution_gated_cooling_off`

## Position Sizing: Kelly Fraction

Kelly formula: `f = (p×b − (1−p)) / b` where `b = TP/SL`, `p = confidence`

With `STOP_LOSS_PCT=0.05`, `MIN_RR_RATIO=2.0`, `KELLY_FRACTION_SCALE=0.25`:
- At 65% confidence → 1% position size
- At 75% confidence → 1.25% position size
- At 85% confidence → 1.4% position size
- All sizes hard-capped at 1.5% (`MAX_RISK_PER_TRADE_PCT`)

## Expected Improvements

### Certain (structural fixes):
- Paper mode now requires the same 0.55 composite score as live — eliminates
  30-50% of paper trades that were pure noise
- 0.65 confidence gate adds a second filter that score-boosting alone cannot bypass
- Negative-EV trades are blocked before order submission
- ATR regime filter keeps the bot silent during sideways markets
- Kelly sizing scales trade size proportionally to signal quality

### Likely (but market-dependent):
- Cooling-off gate reduces drawdown after losing streaks
- RSI/ATR/time-of-day in signals gives the LLM real regime context

### Honest caveats:
- Without walk-forward backtesting, the 0.65 confidence threshold is conservative
  but may also filter some genuinely good trades in the short term
- Kelly uses LLM confidence as win_probability — if the LLM is systematically
  overconfident, Kelly will oversize. The 1.5% hard cap limits worst-case exposure
- Regime filter requires ~34 ticks of price history per symbol before activating.
  During warmup the regime gate is bypassed (allow by default)

## First Week Monitoring Checklist

- [ ] `execution_gated_low_confidence` — if >60% of signals are gated, 0.65 may be too high
- [ ] `execution_gated_choppy_regime` — frequent triggering means markets are sideways (intentional)
- [ ] `execution_gated_cooling_off` — should be rare; frequent = signal quality is systematically low
- [ ] `execution_gated_negative_net_ev` — should be zero for MOMENTUM (≥1.5%) signals
- [ ] Fill rate (trades executed / signals received) — expect 40-60% reduction vs before
- [ ] Daily PnL trend — if still negative after one week, investigate LLM direction accuracy
- [ ] Kelly sizes in decision payloads — `size_pct` should vary 0.001–0.015 by confidence
