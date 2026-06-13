# Cognitive Trading Brain (`cognitive/`)

A deterministic, event-stream-driven, GitOps-evolved multi-agent trading brain.
It implements the full closed feedback loop the system spec describes, wired so
that **every change traces back to measurable PnL** and **behaviour only ever
changes through a reviewed Pull Request**.

It lives outside `api/` on purpose (like `backtest/`): it is the decision core,
not request-path code, so it is exempt from the FieldName guardrail ceremony. It
depends on no Redis, DB, or network — which is exactly what makes it
**deterministic and reproducible**.

## The one closed loop

```
        ┌──────────────── CONFIG (Git-versioned: weights / thresholds / risk) ───────────────┐
        │                                                                                     │
        ▼                                                                                     │
  market ──► agents (news/tech/macro/risk/reasoning) ──► feature aggregation                 │
                 (advisory only)                              │ {news,tech,macro,risk}        │
                                                              ▼                               │
                                                   DECISION ENGINE (pure math)                │
                                          score = Σ signalᵢ·weightᵢ → BUY/SELL/HOLD           │
                                                              ▼                               │
                                                   RISK ENGINE (hard rules)                   │
                                                              ▼                               │
                                                   EXECUTION (deterministic)                  │
                                                              ▼                               │
                                       outcome ─► attribution ─► multi-dim GRADE              │
                                                              ▼                               │
                                       LEARNING ENGINE → observations only                    │
                                                              ▼                               │
                                       PROPOSAL AGENT → typed candidate change                │
                                                              ▼                               │
                                       SHADOW BACKTEST (the judge: Δpnl/Δsharpe/Δdd)           │
                                                              ▼                               │
                                       CHALLENGER (safety validator: approve/reject)          │
                                                              ▼                               │
                                       GITOPS → Pull Request plan ── human merge ─────────────┘
```

Everything above emits a typed event onto the **single `EventStream`** — the one
source of truth. The observability layer is a pure read of that stream.

## Integrity rules (enforced by construction)

| Rule | How it's guaranteed |
|---|---|
| No RL / no hidden learning | `LearningEngine` produces **observations only**; it has no method that writes config or weights (`test_learning_engine_has_no_mutation_methods`). |
| Decision is pure math | `decision.decide()` is a pure function of `(features, weights)`; the `risk` feature is excluded from the score. No LLM/agent can influence it. |
| Backtest is the judge | A proposal is evaluated by a **config-parameterized paired backtest** (`backtest_gate`) before it can become a PR. A proposal with no Δ is invalid. |
| Challenger is a guardrail | `challenger.review()` checks sample size, overfitting (in-sample vs out-of-sample), risk impact, and attribution consistency. It mutates nothing. |
| Behaviour changes only via PR | `evolve()` never mutates `self.config`; only `merge()` (a landed PR) does. PRs are **never auto-merged**. |
| Fully observable & reproducible | Nothing computes durable state off the stream; timestamps are injected, so identical inputs ⇒ identical stream (`test_loop_is_deterministic`). |
| No agent imports another agent | All agents register through `AgentRegistry`; discovery is via the registry. |

## Module map

| Module | Responsibility |
|---|---|
| `events.py` | `EventStream` + `EventType` — the single SYSTEM_EVENT_STREAM. |
| `config.py` | `CognitiveConfig` + bounds validation + safe load (data-not-code, like `param_overrides`). |
| `agents.py` | News / Technical / Macro / Risk / Reasoning specialists (deterministic default scorers, injectable LLM seam). |
| `aggregation.py` | Normalize agent outputs → `{news,tech,macro,risk}` (the only thing the decision engine sees). |
| `decision.py` | Deterministic weighted-sum decision engine. |
| `risk.py` | Hard-rule risk gate (position size / exposure / daily loss). |
| `execution.py` | Deterministic order sizing/record (no reasoning). |
| `learning.py` | Attribution, `ImportanceTracker` (metadata), `LearningEngine` (observations only). |
| `grading.py` | Multi-dimensional grades for trades (Direction/Risk/Execution/Timing), agents, proposals, config versions. |
| `proposal.py` | `ProposalType` hierarchy, `ProposalAgent` (architect), `ProposalScorecard` (success-rate-by-type), `ProposalQueue`. |
| `challenger.py` | Safety validator (approve/reject + risk score + reasons). |
| `backtest_gate.py` | Config-parameterized paired backtest → `{pnl,sharpe,drawdown,false-positive}` deltas. |
| `gitops.py` | Branch name, config diff, PR body, bounds-safe config apply. No auto-merge. |
| `registry.py` | `AgentRegistry` — central agent discovery. |
| `health.py` | Cognitive wiring health (agents, pipeline funnel, learning coverage) from the stream. |
| `trace.py` | Per-trade "why did we?" chain reconstruction from the stream. |
| `loop.py` | `CognitiveLoop` — wires every stage, emits typed events, and produces the 7-tab snapshot. |
| `demo.py` | Deterministic seeded trajectory — standalone, exercised by this package's own tests. **No longer served by the observability API** (the dashboard shows live agents only). |

## Observability API (read-only)

Mounted at `/cognitive` (and `/api/cognitive`). **Every endpoint is LIVE** —
backed by `api/services/cognitive_live.py` (the real agent pipeline), never the
seeded `demo.py` trajectory. The dashboard reads `/state` + `/events`.

| Endpoint | Returns |
|---|---|
| `GET /cognitive/state` | Full live snapshot (single UI data source). |
| `GET /cognitive/events` | The recent real event stream (recent N). |
| `GET /cognitive/config` | Active live config (prompt-directive version + IC weights). |
| `GET /cognitive/agents` | Live agent roster. |
| `GET /cognitive/trace/{trace_id}` | Live decision + perception chain for one trade. |

## Tests

```
tests/core/test_cognitive_core.py        # stream, config, agents, aggregation, decision, risk, execution
tests/core/test_cognitive_grading.py     # multi-dimensional grading
tests/core/test_cognitive_learning.py    # attribution, importance, observations (no mutation)
tests/core/test_cognitive_evolution.py   # proposal/scorecard/challenger/backtest gate/gitops
tests/integration/test_cognitive_loop.py # full loop: determinism, invariants, snapshot
tests/api/test_cognitive_routes.py       # the read-only API
```

## Requested-feature coverage map

Substantially implemented: single event stream, 5 cognitive specialists, feature
aggregation, deterministic decision engine, hard risk engine, deterministic
execution, attribution, multi-dimensional grades (trade/agent/proposal/config),
observations-only learning, first-class ProposalAgent with `ProposalType`
hierarchy + success-rate scorecard, shadow/paired backtest (baseline vs
candidate), challenger guardrail, GitOps PR plans with full diff + evidence (no
auto-merge), proposal lifecycle queue, evolution timeline, per-trade trace view,
cognitive health, append-only event history (truth preservation), agent registry.

Hardening pass (review-driven, now implemented):
  * **Walk-forward validation** — `backtest_gate.walk_forward` evaluates a
    candidate across several sequential market periods; the challenger requires
    ≥60% fold consistency, so a one-window fluke can't be promoted.
  * **News is genuinely backtested** — the gate accepts a per-bar sentiment
    series, so news-weight proposals actually move the backtest (previously news
    was constant-0 and inert).
  * **Proposal governance** — `governance.ProposalGovernor` enforces a per-window
    quota, exact-duplicate dedup, and a cooldown that benches a target whose
    proposal was rejected (novelty / retirement).
  * **Per-trade config lineage** — every decision / execution / outcome event
    stamps `config_version` + `config_proposal_id`; the trace surfaces it, so
    "which merged proposal caused this drawdown?" is answerable.
  * **Event-stream retention** — `EventStream(max_events=…)` evicts the oldest
    events while `seq` stays monotonic; `dropped`/`emitted` are reported in health.
  * **Risk independence** — pinned by a stream invariant test: no EXECUTION event
    exists without a RISK_GATE in the same trace.
  * **Decision counterfactuals** — `counterfactual.py`: every closed trade records
    what BUY/SELL/HOLD would each have returned on the realized move, the best
    action, and the regret of the one taken (so a good-but-unlucky decision isn't
    mistaken for a bad one). Surfaced on the trace and as a decision-quality KPI.
  * **Drift detection** — `drift.py`: a `DriftMonitor` watches rolling streams
    (trade-grade quality, decision regret, direction hit-rate) and emits a typed
    `DRIFT` alert when the recent window degrades materially vs the prior window.

Roadmap (designed-for, not yet built): richer regime detection + per-regime
grading, meta-grading, forecasting accountability, full knowledge graph /
lineage explorer, system replay UI, digital twin, research workbench. The
append-only stream + config-version lineage are the substrate these build on.
