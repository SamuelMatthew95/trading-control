# Backtest, Grades, and the Challenger Loop

How the system learns whether it is making money — and how it changes itself.

## The loop

```
 live trades ──▶ GradeAgent (trade_scorer) ──▶ grades: A–F, win rate, IC, mistake tags
      ▲                                                       │
      │                                                       ▼
 promote / retire ◀── challenger verdict ◀── backtest harness ◀── candidate strategy
   (ChallengerAgent)     different? better?    (same signal + scorer, run offline)
```

1. **Live trades** flow through the agents (SignalGenerator → ReasoningAgent →
   ExecutionEngine) and are graded by the **GradeAgent** using `trade_scorer`
   — win rate, Sharpe, information coefficient, and *which mistakes* cost money
   (tagged: `execution_drag`, `late_entry`, `adverse_price_move`, …).
2. The **backtest harness** replays the *same* `classify_signal` and the *same*
   `trade_scorer` over price history **offline**, so we can ask "would this
   change make money?" *before* risking capital. It is exposed at
   `GET /backtest/compare` and shown in the dashboard's Learning section.
3. A **candidate strategy** (`backtest/strategies.py`) is judged by the
   **challenger verdict** (`backtest/challenger.py`): it must be **different**
   from the baseline *and* **beat** it to be recommended for **promotion**;
   anything else is **rejected**. This is the "active and not just doing the
   same thing as the others" gate.
4. The live **ChallengerAgent** carries a candidate config and, on retirement,
   attaches this backtest verdict to its summary — turning a vague win-rate
   readout into a real promote/retire recommendation on the `proposals` stream.

## What we can learn

| Source | Tells us |
|---|---|
| Grades (`trade_scorer`) | Win rate, Sharpe, IC, and *which* mistakes are losing money |
| Backtest `/compare` | Whether a strategy makes or loses money, on real or synthetic data |
| Challenger verdict | Whether a proposed change is genuinely different **and** better |

The headline the harness already surfaced: the **baseline over-trades noise**
(≈240 trades, deeply negative on a zero-edge series), while selective
strategies trade far less and lose far less. *That* is where the money leaks —
trading cost on signals with no edge.

## How an agent actually changes

1. ReflectionAgent / StrategyProposer surface a hypothesis → a candidate strategy.
2. The candidate runs through `/backtest/compare`; the **challenger verdict**
   says `promote` or `reject`.
3. A `promote` verdict is the green light to update the live `classify_signal`
   (thresholds / strategy). A `reject` keeps the incumbent. **Nothing ships
   without beating the baseline in the harness first** — no more blind changes.

## Real vs backtest provenance

`/backtest/compare` returns `source: "alpaca" | "synthetic"`:

- **`alpaca`** — real market history (on the deployed backend, where the Alpaca
  keys live). A positive return here is *genuine edge*.
- **`synthetic`** — a deterministic zero-drift series (local / CI / when the
  network allowlist blocks Alpaca). The only signal here is "trades less, loses
  less" — never mistake it for alpha.

## Safe evolution: lifecycle + circuit breaker

A strategy never graduates straight to production. It is a **versioned,
immutable** record in the registry (`api/services/strategy_registry.py`) that
advances one stage at a time and **cannot skip**:

```
proposed → backtested → shadow → canary → live → retired
```

- Exactly one version is `live`; promoting a new one supersedes the incumbent.
- `rollback()` restores the previous live version.
- The **circuit breaker** (`api/services/circuit_breaker.py`) trips on a
  drawdown / failure / divergence / latency breach — it flips the existing kill
  switch and rolls back. Fail-closed.

### See it on the dashboard (Learning section)

- **Backtest — Strategy Comparison** + challenger verdict — `GET /backtest/compare`.
- **Strategy Lifecycle** — every version and its stage, plus a "circuit breaker
  tripped" badge — `GET /backtest/strategies`.

> Status: the registry is seeded from the known strategies (baseline `live`, the
> rest `backtested`). Wiring the StrategyProposer/challenger to register versions,
> and calling the breaker inside the live execution loop, are the next steps.

## Durable shadow track record + graduation

A `ChallengerAgent` shadow-trades its strategy on every live tick, but its
`ShadowMetrics` used to live only in process memory — so every Render cold start
reset them to zero and a challenger could never accumulate the
`CHALLENGER_MIN_SHADOW_TRADES` it needs to earn a promotion proposal. The loop
*looked* dead because the evidence kept evaporating.

- **Durable record** — `api/services/challenger_store.py` (`ChallengerStore`,
  Redis hash `challenger:perf:{strategy}`, no TTL, keyed by strategy because
  challenger ids are ephemeral). The agent persists on every realized shadow
  round-trip and warm-starts from it on boot, reconstructing both engines from
  the persisted per-trade PnL lists so the metrics are exactly what they were
  before the restart. Same durability rationale as `agent_pnl_store` — Redis,
  not InMemoryStore (wiped on restart) or Postgres (absent in this deployment).
- **Backend decides the state** — `activity_snapshot()` emits a
  `learning_status` (`ChallengerLearningStatus`: warming → building → eligible →
  promotion_proposed → graduated) and a `shadow_edge` (own − baseline PnL). The
  UI only renders these; it never re-derives the state.
- **Graduation** — when an approved/auto promotion is applied, `ProposalApplier`
  stamps the record `graduated` AND advances the strategy registry one stage
  (SHADOW → CANARY, gated on `CHALLENGER_GRADUATE_TO_CANARY`) — the "modularize
  the winner" half of the loop, on top of the prompt-directive bias + candidate
  spawn. Still no live orders; purely registry + record state.
- **Surfaced on the Learning page** — `/dashboard/learning` shows each rival
  strategy's durable track record (trades, win rate, PnL, edge vs baseline) and
  where it sits in the loop, so the learning evidence lives where the operator
  looks for it (not only on `/dashboard/challengers`).

## Try it

```bash
# The API the dashboard uses (real data on Render, synthetic locally):
curl localhost:8000/backtest/compare | jq

# Strategy lifecycle stages + circuit-breaker state:
curl localhost:8000/backtest/strategies | jq
```

```python
# Ad-hoc, in Python:
from backtest.compare import compare_on_prices
from backtest.data import synthetic_prices
for s in compare_on_prices(synthetic_prices(n=1500, vol_pct=1.5)):
    print(s.name, s.mean_return_pct)
```

Harness internals: [`backtest/README.md`](../backtest/README.md).
Troubleshooting: [`docs/troubleshooting/`](./troubleshooting/).
