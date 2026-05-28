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

## Tests

`tests/integration/test_backtest_flow.py` (CI-gated): end-to-end run,
determinism, and the reproduced "idle" failure mode.
