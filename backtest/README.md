# Backtest Harness

Offline measurement for the trading-control signal logic.

## Why this exists

The live system is event-driven and only ever learns *after* it has already
traded — and lost. Before this harness there was **no way to ask "would this
rule have made money?"** without deploying it to the live (paper) loop and
waiting for real losses to accumulate. Every strategy change shipped blind.

This package closes that gap. It replays a price series through the **exact
production decision** and **exact production scorer**, offline, in
milliseconds:

```
prices ─▶ classify_signal() ─▶ simulated fills ─▶ trade_scorer ─▶ metrics
         (api.services.            (paper-broker      (api.services.agents.
          signal_generator)         slippage model)    trade_scorer)
```

It deliberately **reuses** production code rather than reimplementing it, so the
backtest and the live system can never silently diverge. Change the signal and
the harness measures the real thing.

## Design

| Concern | Where | Note |
|---|---|---|
| Buy/sell/hold decision | `api.services.signal_generator.classify_signal` | Single source of truth, shared with the live agent |
| Fill simulation | `backtest/engine.py` | Mirrors `execution/brokers/paper.py` slippage (0.01%–0.05%) |
| Per-trade scoring & metrics | `api.services.agents.trade_scorer` | Same Sharpe / win-rate / drawdown the live grades use |
| Price data | `backtest/data.py` | Seeded random walk (CI) or real Alpaca 1-min bars |

It lives **outside `api/`** on purpose: this is research tooling, not
request-path code, so it is exempt from the `FieldName`/guardrail conventions
that govern the live service. It imports *from* `api` but is never imported
*by* it.

The engine is pure and synchronous — no Redis, no DB, no async — and fully
deterministic for a given `slippage_seed`, which is what makes it testable.

## Usage

```bash
# Synthetic data (always available, no credentials needed)
python -m backtest --symbol BTC/USD --bars 2000 --vol 0.8

# Realistic per-minute volatility — reproduces the "idle / 0 trades" mode
python -m backtest --bars 2000 --vol 0.1

# Real historical data (requires ALPACA_API_KEY / ALPACA_SECRET_KEY)
python -m backtest --symbol BTC/USD --bars 1000 --source alpaca

# Run a specific strategy, or compare them all head-to-head
python -m backtest --strategy confirmed_trend --vol 1.5
python -m backtest --compare --vol 1.5
```

```python
from backtest import run_backtest
from backtest.data import synthetic_prices

result = run_backtest(synthetic_prices(n=2000, vol_pct=1.5, seed=1))
print(result.summary())
print(result.total_return_pct, result.sharpe, result.win_rate)
```

## What it revealed

Running the **current** signal over a zero-edge random walk (no drift — there is
no edge to find, so any P&L is the signal's own behavior plus trading cost):

| Regime | Trades | Return | Win rate | Sharpe |
|---|---|---|---|---|
| Realistic vol (0.1%/bar) | 0 | +0.00% | — | — |
| Elevated vol (1.5%/bar) | 339 | **−54.65%** | 33.6% | −0.89 |

The signal either never trades, or — when volatility is high enough to cross its
1.5%/3.0% thresholds — chases momentum into noise (buys the spike, sells the
dip), wins only a third of the time, and bleeds out through slippage. This is
the baseline any future strategy change must beat **in the harness** before it
goes anywhere near live capital.

## Pluggable strategies

The decision is a swappable `Strategy` (`backtest/strategies.py`) — a function
from one bar of context to `"buy"` / `"sell"` / `"hold"`. `baseline_momentum`
*is* the live `classify_signal`; the rest are hypotheses measured against it.
`backtest/compare.py` runs them over identical seeded price paths and averages
the results.

```
$ python -m backtest --compare --vol 1.5
strategy               return%   trades   sharpe    win%
--------------------------------------------------------
confirmed_trend           5.71     24.0    0.589   43.3%
strong_only              -6.05     35.0   -0.282   40.1%
mean_reversion          -16.18    241.5   -0.175   62.0%
baseline_momentum       -22.15    241.5   -0.347   36.8%
```

**How to read this honestly:** the data has no edge by construction, so the
*only* lever is trading cost. The baseline's flaw is laid bare — it makes 241
trades and bleeds −22% to slippage. Strategies that trade selectively (24–35
trades) cut that loss by 70–100%. `confirmed_trend` edging *positive* here is
**within sampling noise** on a zero-edge walk — it is evidence of *not
over-trading*, **not** evidence of alpha. A genuinely profitable strategy can
only be confirmed on **real market data** (`--source alpaca`). What this proves
is the methodology: a change can now be measured before it ever risks capital.

## API + dashboard UI

The harness is exposed as an **on-demand, cached** endpoint — not a one-off
script and not a constant re-run:

- `GET /backtest/compare?symbol=BTC/USD&bars=750` (`api/routes/backtest.py`)
  runs the comparison and returns JSON. On the deployed backend (Render) it
  fetches **real Alpaca history**; locally / in CI it falls back to a
  deterministic synthetic series and says so via `source` (`alpaca` |
  `synthetic`).
- Results are **memoized per `(symbol, bars)`** for 10 minutes, so polling the
  panel or reloading the page does not recompute the backtest or re-hit the
  rate-limited data API. The `cached` flag tells you which you got.
- The dashboard's **Backtest — Strategy Comparison** panel
  (`frontend/src/components/dashboard/BacktestComparisonPanel.tsx`) lives in the
  Learning section and fetches once on mount, with a manual Refresh button — no
  timer.

**Why it's integrated, not an island:** the endpoint calls the *same*
`classify_signal` the live SignalGenerator agent uses and the *same*
`trade_scorer` the GradeAgent uses. Change the signal and both the live agents
and this panel move together — one source of truth, so the backtest measures
exactly what the agents do.

## Tests

`tests/integration/test_backtest_flow.py` (CI-gated): end-to-end run,
determinism, the reproduced "idle" failure mode, that the pluggable refactor
preserves baseline behavior, and that a selective strategy beats the baseline
across 20 paired seeds.
