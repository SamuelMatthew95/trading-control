# The Learning Loop — buy → sell → grade → learn → propose → PR

This is the end-to-end story of how a trade becomes a graded outcome, how that
feeds learning, and how learning eventually proposes a parameter change as a
GitHub PR for human review. Every hop is a Redis stream and every consumer is a
real agent — nothing here is a mock.

## The full chain

```
PricePoller ── market_events ──▶ SignalGenerator ── signals ──▶ ReasoningAgent
                                                                      │
                                                              decisions (advisory)
                                                                      │
                                                                      ▼
                                                               ExecutionEngine
                                          (gates: confidence, score, regime, EV, cooling-off)
                                                                      │
                       ┌──────────────────────────────────────────────┼─────────────────────────┐
                       ▼                          ▼                     ▼                          ▼
                  executions            trade_performance        trade_completed            trade_lifecycle
                       │                          │                     │
        ┌──────────────┼──────────────┐           │            ┌────────┴────────┐
        ▼              ▼              ▼            ▼            ▼                 ▼
   GradeAgent     ICUpdater     ChallengerAgent  (each agent has its OWN consumer group — fan-out,
        │              │              │            not load-balanced; see "Fan-out" below)
   agent_grades   factor_ic_history   │
        │              │         (also consumes `signals` to run its strategy as SHADOW trades)
        ▼              ▼
   ReflectionAgent ◀───┘
        │
   reflection_outputs
        │
        ▼
   StrategyProposer ── proposals ──▶ ProposalApplier
        │                                   │
        │                    ┌──────────────┼───────────────────────────┐
        │                    ▼              ▼                            ▼
        │           signal_weight      agent_suspend / trading_pause   PARAMETER_CHANGE
        │           (Redis control)    (Redis control)                       │
        │                                                            github_prs (pr_request)
        │                                                                     │
        └─ github_prs (rule/code change PRs)                                  ▼
                                                          GET /learning/pending-param-changes
                                                                     │
                                                          param-evolution-pr.yml (scheduled)
                                                                     │
                                                     edits config/param_overrides.json on a branch
                                                                     │
                                                                opens a PR  ──▶  human review/merge
                                                                     │
                                              api/constants.py reads + validates the override at startup
```

## Why every decision used to be `hold` (and how it was fixed)

The whole loop sat idle for one reason: **no buy/sell ever executed**, so the
downstream agents were starved (0 events). Three compounding bugs, fixed root-first:

1. **`pct` pinned to 0** — PricePoller derived the price-change `pct` from the
   Redis price cache, whose TTL was shorter than the poll interval, so the prev
   price had always expired → `pct=0` → every signal `LOW`/`NEUTRAL` → `hold`.
   Fixed: the poller keeps its own in-memory prev-price anchor.
   (`docs/troubleshooting/price-poller.md`.)
2. **Contradictory gates** — `SIGNAL_CONFIDENCE_MIN_GATE` (0.65) sat *above* the
   MOMENTUM tier (0.55) the execution-score gate was tuned to admit, so no
   momentum trade could ever pass both. Fixed: lowered to 0.50.
   (`docs/troubleshooting/execution-engine.md`.)
3. **Cache empty between polls** — `REDIS_PRICES_TTL_SECONDS` (30s) < stock poll
   interval (60s). Fixed: raised to 150s.

## Fan-out: each learning agent has its OWN consumer group

`GradeAgent`, `ICUpdater`, `ReflectionAgent`, and `ChallengerAgent` all consume
shared streams like `trade_performance`. They used to share ONE Redis consumer
group (`workers`), which **load-balances** — each event went to only ONE of them,
silently starving the others. Each agent now uses its own group
(`workers:{consumer}`) so it receives EVERY event. See
`api/services/agents/base.py` (`self._group`).

## Challengers actually run their strategy (shadow trading)

A `ChallengerAgent` is spawned per non-baseline strategy (`mean_reversion`,
`confirmed_trend`, `strong_only`). It used to just grade the baseline's fills —
the strategy config was decorative. Now it consumes `signals` and feeds prices to
a `ShadowTradeEngine` (`api/services/shadow_trader.py`) that runs BOTH its strategy
and the baseline as paper "shadow" trades — no real capital. Its grade and
retirement payloads carry the real own-vs-baseline evidence (`shadow_trades`,
`shadow_win_rate`, `shadow_pnl`, `beats_baseline_shadow`), surfaced on the
dashboard's Learning Loop panel.

## Parameter evolution is GitOps — data, not code

When the loop wants to tune a parameter (e.g. after grades show a gate is too
tight), `ProposalApplier` does NOT mutate anything at runtime. It publishes a
structured `pr_request` to `github_prs`. The scheduled `param-evolution-pr.yml`
workflow reads `GET /learning/pending-param-changes`, edits
**`config/param_overrides.json`** (plain data, never source code) on a dedicated
`param-evolution/<PARAMETER>` branch, and opens a PR. On merge + restart,
`api/constants.py` reads and re-validates the override (against the same
`PARAM_BOUNDS`), applying it over the code default — or ignoring it if it's
out of bounds. A bad artifact can never break the running app.

| Layer | File | Tested by |
|---|---|---|
| Safe bounds + validation | `api/services/param_evolution.py` | `tests/core/test_param_evolution.py` |
| Override loader (data) | `api/services/param_overrides.py` | `tests/core/test_param_overrides.py` |
| Apply at import | `api/constants.py` (`ACTIVE_PARAM_OVERRIDES`) | `tests/core/test_param_overrides.py` |
| File-IO CLI | `scripts/apply_param_change.py` | `tests/core/test_apply_param_change_script.py` |
| PR planning (branch/dedup/base) | `scripts/param_evolution_runner.py` | `tests/core/test_param_evolution_runner.py` |
| The thin workflow shell | `.github/workflows/param-evolution-pr.yml` | (runs the tested runner) |
| Surfacing endpoint | `api/routes/learning.py::get_pending_param_changes` | `tests/api/test_learning_routes.py` |

## What is observable in the UI

The dashboard's **Learning Loop** panel (`frontend/.../LearningLoopPanel.tsx`,
rendered in the Agents section) shows: latest grade, trading-paused state, signal
weight, applied/pending proposal counts, suspended agents, loss attribution, the
challenger shadows (with strategy name + shadow win/PnL + "beats baseline" badge),
and the pending parameter-change PRs (current → proposed + reason).

## What is honest about the current state

- The pipeline now TRADES and the loop RUNS end-to-end — but the strategies have
  **no proven edge** (backtest is red on real BTC; small-move crypto momentum is
  close to a coin-flip after costs). The machine that hunts for an edge is built;
  whether an edge exists is the market's answer.
- With Postgres down (memory mode), IC is degraded (`composite_score` defaults to
  0.5) and there's no durable history. Bring the DB up for real learning.
