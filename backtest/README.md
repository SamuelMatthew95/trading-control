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

The single entrypoint is the API (`GET /backtest/compare`, see below). For
tests and ad-hoc use there is a small Python surface:

```python
from backtest import run_backtest
from backtest.compare import compare_on_prices
from backtest.data import synthetic_prices

prices = synthetic_prices(n=2000, vol_pct=1.5, seed=1)

# One strategy
result = run_backtest(prices)
print(result.total_return_pct, result.sharpe, result.win_rate)

# All strategies, head to head on the same series
for s in compare_on_prices(prices):
    print(s.name, s.mean_return_pct, s.mean_trades)
```

Real Alpaca history is used automatically when `ALPACA_API_KEY` /
`ALPACA_SECRET_KEY` are set (i.e. on the deployed backend); otherwise the
harness falls back to a deterministic synthetic series.

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
`backtest/compare.py` runs them over the same price series. Representative
result (synthetic, zero-edge, mean over 20 seeds):

```
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
only be confirmed on **real market data** (`source=alpaca`, on the deployed
backend). What this proves
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
  Learning section and fetches once on mount, with a **Run now** button that
  forces a fresh recompute (`?force=true`, bypassing the cache).
- A background loop (`run_backtest_refresh_loop`, started in `api/main.py`)
  warms the cache on boot and **refreshes it every hour**
  (`BACKTEST_REFRESH_INTERVAL_SECONDS`) so the panel shows fresh real-data
  results without anyone clicking.

**Why it's integrated, not an island:** the endpoint calls the *same*
`classify_signal` the live SignalGenerator agent uses and the *same*
`trade_scorer` the GradeAgent uses. Change the signal and both the live agents
and this panel move together — one source of truth, so the backtest measures
exactly what the agents do.

## Shadow lifecycle — candidates run, but place no orders

A strategy must not jump straight to live. The lifecycle enforces it:

```
proposed → backtested → shadow → canary → live
```

`baseline_momentum` is the one **live** signal (it *is* `classify_signal`). The
other strategies are wired into **shadow**: at startup `api/main.py` spawns one
`ChallengerAgent` per non-baseline strategy in `STRATEGIES`. A shadow challenger:

- consumes the live `executions` / `trade_performance` streams,
- is graded under its own `instance_id`,
- **places no orders**, and
- registers itself at `SHADOW` in the `StrategyRegistry`
  (`api/services/strategy_registry.py`) so it shows on the dashboard's Strategy
  Lifecycle panel.

Registration is **eager** (on `ChallengerAgent.start()`, not on the first fill)
and **idempotent** (`registry.find_by_strategy`), so a candidate appears in
shadow as soon as the app boots — even while the pipeline is idle — and the route
seeder (`_ensure_registry_seeded`) and the challengers never double-register.
Promotion shadow → canary → live stays a deliberate, gated step; nothing skips it.

## Distribution telemetry — calibration as evidence

`GET /backtest/distribution?symbol=BTC/USD&bars=750` (`backtest/distribution.py`)
answers *"is a 1.5% single-bar trigger even reachable on this timeframe?"* For
each timeframe (1/5/15/60 base-bar multiples) it reports the distribution of
`|per-bar move|` and where the live `MOMENTUM_PCT` / `STRONG_MOMENTUM_PCT`
thresholds fall in it:

```
timeframe   p50     p95     p99     1.5% → percentile   1.5% → hit_rate
1-bar       0.04%   0.18%   0.31%   p99.7               0.3%
60-bar      0.31%   1.42%   2.65%   p82.0               18%
```

This makes mis-calibration *visible* — "1.5% is a p99.7 event on 1-minute bars"
becomes a number, not a hunch — and is the groundwork for volatility-normalized
triggering (`move > k·rolling_σ`), for which the report already surfaces a
rolling-sigma summary per timeframe. Cached per `(symbol, bars)` like `/compare`.

The dashboard's **Move Distribution — Threshold Calibration** panel
(`frontend/src/components/dashboard/DistributionPanel.tsx`, Learning section)
renders it: per-timeframe `|move|` percentiles and each live trigger's tail
percentile + fire rate, with deep-tail (≥ p99) triggers flagged in red so an
unreachable threshold is obvious at a glance.

## Tests

- `tests/integration/test_backtest_flow.py` (CI-gated): end-to-end run,
  determinism, the reproduced "idle" failure mode, the pluggable refactor
  preserving baseline behavior, a selective strategy beating the baseline across
  20 paired seeds, and the `INSUFFICIENT_DATA` eligibility gate.
- `tests/integration/test_distribution.py` (CI-gated): the move-distribution
  telemetry — percentiles, threshold percentile / hit-rate, and that coarser
  timeframes shift the thresholds to lower percentiles.
- `tests/agents/test_challenger_agent.py`: shadow registration is eager and
  idempotent (exactly one lifecycle entry per strategy).
- `tests/core/test_strategy_registry.py`: `find_by_strategy` lookup.
- `tests/api/test_backtest_route.py`: `/compare`, `/distribution`, and the
  lifecycle states (`baseline_momentum` live, candidates shadow).
