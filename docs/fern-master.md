# Trading Control — Complete Platform Documentation

> **This is the single master reference for the Trading Control platform.**
> It covers architecture, agents, learning loop, storage, LLM integration, API,
> frontend, development, testing, deployment, and operational guardrails — everything
> needed to understand, run, extend, or operate the system.

---

## Table of Contents

1. [Why This Exists](#1-why-this-exists)
2. [Platform Snapshot](#2-platform-snapshot)
3. [System Architecture](#3-system-architecture)
4. [The 7-Agent Pipeline](#4-the-7-agent-pipeline)
5. [The Cognitive Brain (Deterministic Layer)](#5-the-cognitive-brain-deterministic-layer)
6. [The Learning Loop](#6-the-learning-loop)
7. [Self-Evolving Directives](#7-self-evolving-directives)
8. [Decision Provenance](#8-decision-provenance)
9. [Storage Architecture](#9-storage-architecture)
10. [Database Schema (v3)](#10-database-schema-v3)
11. [LLM Integration](#11-llm-integration)
12. [Memory-Mode Resilience](#12-memory-mode-resilience)
13. [API Overview](#13-api-overview)
14. [Frontend Dashboard](#14-frontend-dashboard)
15. [Development Guide](#15-development-guide)
16. [Deployment Guide](#16-deployment-guide)
17. [Testing Guide](#17-testing-guide)
18. [Key Guardrails and Conventions](#18-key-guardrails-and-conventions)
19. [Configuration Reference](#19-configuration-reference)
20. [Troubleshooting Quick Reference](#20-troubleshooting-quick-reference)

---

## 1. Why This Exists

Trading Control keeps algorithmic execution **adaptive without sacrificing determinism**.

- AI agents can reason, reflect, and propose improvements to their own strategy directives.
- Infrastructure enforces idempotency, traceability, and safe persistence routes at every step.
- Operators retain real-time observability, manual override capability, and human approval gates on all proposed parameter changes.

The goal is a machine that hunts for a trading edge, documents its reasoning, learns from outcomes, proposes its own improvements, and never does anything irreversible without human approval.

---

## 2. Platform Snapshot

| Layer | Technology | Purpose |
|---|---|---|
| Backend | FastAPI (Python 3.10+) on Render | APIs, orchestration, event ingestion |
| Frontend | Next.js 14 (TypeScript) on Vercel | Operator dashboard and control plane |
| Database | PostgreSQL 15+ with pgvector | Durable state, audit history, vector memory |
| Event bus | Redis Streams | Agent-to-agent communication and fan-out |
| Cache / control | Redis KV | Shared mutable state (prices, weights, kill switch) |
| Broker | Alpaca (paper trading mode) | Market data and execution simulation |
| LLM | Gemini (default), Groq, Anthropic, OpenAI, LM Studio | ReasoningAgent, ReflectionAgent, StrategyProposer |
| Cognitive layer | Python (`cognitive/`) | Deterministic event-stream brain — math only, no LLM in the decision path |

---

## 3. System Architecture

### High-Level Flow

```
Market Data (Alpaca)
       │
       ▼
  PricePoller  ──── market_ticks ────▶  Agent Pipeline (7 agents)
       │                                        │
       │                               (Redis Streams — event bus)
       │                                        │
       │                               (PostgreSQL — durable history)
       │                                        │
       ▼                                        ▼
  Cognitive Brain                     Next.js Dashboard
  (deterministic event-stream loop)   (REST + WebSocket hydration)
```

### Core Architecture Principles

| Principle | How it works |
|---|---|
| **Event-driven** | Agents communicate exclusively via Redis Streams — never by calling each other directly |
| **Idempotency** | Orders and events carry `idempotency_key`; duplicate events are silently dropped at the DB layer |
| **Traceability** | `trace_id` flows from the first tick through every agent run, log entry, and vector memory record |
| **Deterministic writes** | `SafeWriter` is the only write path; `determine_persist_route()` selects DB / MEMORY / SKIP before attempting any write |
| **Memory-first resilience** | `is_db_available()` routing switch; when false, dashboard reads short-circuit to `get_runtime_store()` before any SQL session is created |
| **Replayability** | The `events` table is an append-only ledger that can rebuild operational state |
| **Schema version** | Every new insert uses `schema_version='v3'` |

### Repository Layout

```
trading-control/
├── api/                        # FastAPI backend
│   ├── main.py                 # App wiring, middleware, lifespan
│   ├── config.py               # All env vars (Pydantic settings)
│   ├── constants.py            # Redis keys, TTLs, agent names, FieldName enum (~720 members)
│   ├── observability.py        # log_structured() — the only logging function
│   ├── runtime_state.py        # is_db_available() + InMemoryStore singleton
│   ├── schema_version.py       # DB_SCHEMA_VERSION = "v3"
│   ├── events/bus.py           # Redis Streams EventBus
│   ├── routes/                 # HTTP endpoint modules (22 files)
│   ├── services/
│   │   ├── agents/             # All 12 agent implementations
│   │   ├── execution/          # ExecutionEngine + sub-modules
│   │   ├── dashboard/          # Dashboard aggregation services
│   │   ├── agent_heartbeat.py  # Shared heartbeat writer
│   │   ├── redis_store.py      # Capped Redis lists (notifications, decisions, LLM metrics)
│   │   ├── metrics_aggregator.py
│   │   ├── llm_router.py       # Multi-provider LLM routing
│   │   └── prompt_store.py     # Evolved directive versioning
│   └── core/
│       ├── models/             # SQLAlchemy ORM models
│       └── safe_writer.py      # Canonical write path
├── frontend/                   # Next.js 14 operator dashboard
├── cognitive/                  # Deterministic event-stream cognitive brain
├── backtest/                   # Strategy backtesting
├── config/                     # param_overrides.json, cognitive_config.json
├── tests/                      # core/, api/, agents/, integration/
├── docs/                       # Architecture docs and troubleshooting playbooks
└── .github/workflows/          # CI/CD (backend + frontend + param-evolution)
```

---

## 4. The 7-Agent Pipeline

### Pipeline Diagram

```
PricePoller ── market_ticks ──▶ SignalGenerator
                                       │
                                    signals
                                       │
                                       ▼
                                ReasoningAgent (LLM)
                                       │
                                   decisions
                                       │
                                       ▼
                                ExecutionEngine
                          ┌────────────┼────────────┐
                          ▼            ▼             ▼
                      executions  trade_performance  trade_lifecycle
                          │            │
              ┌───────────┼────────────┼───────────┐
              ▼           ▼            ▼            ▼
          GradeAgent  ICUpdater  ChallengerAgent  NotificationAgent
              │           │
        agent_grades  factor_ic_history
              │
       ReflectionAgent (LLM)
              │
       reflection_outputs
              │
       StrategyProposer (LLM)
              │
          proposals
              │
       ProposalApplier
       (GitOps handler-map)
```

### Stream Chain

| Stream | Producer | Consumer(s) |
|---|---|---|
| `market_ticks` | PricePoller (Alpaca) | SignalGenerator |
| `market_events` | PricePoller | Dashboard / WebSocket |
| `signals` | SignalGenerator | ReasoningAgent, ChallengerAgent |
| `decisions` | ReasoningAgent, RiskGuardian | ExecutionEngine |
| `executions` | ExecutionEngine | GradeAgent, ICUpdater, NotificationAgent |
| `trade_performance` | ExecutionEngine | GradeAgent, ICUpdater, ReflectionAgent, ChallengerAgent |
| `trade_completed` | ExecutionEngine (round-trips only) | GradeAgent |
| `trade_lifecycle` | ExecutionEngine | Dashboard / WebSocket |
| `agent_grades` | GradeAgent | Dashboard |
| `factor_ic_history` | ICUpdater | ReflectionAgent |
| `reflection_outputs` | ReflectionAgent | StrategyProposer |
| `proposals` | StrategyProposer | NotificationAgent, ProposalApplier |
| `notifications` | NotificationAgent | Dashboard / WebSocket |
| `risk_alerts` | RiskGuardian, AgentSupervisor | NotificationAgent |
| `agent_logs` | All agents | NotificationAgent |
| `dlq` | DLQManager | DLQManager (retry) |

**Fan-out rule:** `GradeAgent`, `ICUpdater`, `ReflectionAgent`, and `ChallengerAgent` all consume `trade_performance`. Each uses its own Redis consumer group (`workers:{consumer}`) so every agent receives every event — not a round-robin load-balance.

### Agent Responsibilities

#### SignalGenerator

- **Input:** `market_ticks` (Alpaca price data)
- **Output:** typed signal → `signals` stream
- **Logic:** Normalizes tick price changes into three signal tiers:
  - `STRONG_MOMENTUM` — price change ≥ 3%
  - `MOMENTUM` — price change ≥ 1.5%
  - `PRICE_UPDATE` — all other changes (pass-through, no action expected)
- **Trigger:** fires every `SIGNAL_EVERY_N_TICKS` ticks (configurable)
- **Writes to:** `agent_runs`, `agent_logs`
- **Note:** The poller keeps its own in-memory prev-price anchor to avoid the TTL-expiry zero-delta bug

#### ReasoningAgent

- **Input:** `signals`
- **Output:** decision (`BUY` / `SELL` / `HOLD` / `REJECT`) → `decisions` stream
- **Logic:** LLM-powered decision with a layered prompt:
  1. Immutable **constitution** (safety/capital preservation rules)
  2. **Adaptive directive** (evolved by the learning loop; read from `PromptStore`)
  3. **Market context** (current signal, IC weights, vector memory search)
  4. Optional **self-critique** pass for high-confidence decisions (configurable)
- **LLM fallback modes:** `reject_signal` (default — emit REJECT, never a naive buy), `skip_reasoning`
- **Token budget:** daily token cap configurable; exceeding it triggers REJECT
- **Signal dedup:** identical symbol+price within `REASONING_DEDUP_PRICE_PCT` is skipped (cooldown)
- **Writes to:** `decisions:recent` (Redis list), `agent_logs`, `agent_runs`, vector memory

#### ExecutionEngine

- **Input:** `decisions`
- **Output:** `executions`, `trade_performance`, `trade_lifecycle`
- **Gates before execution:** confidence score, regime check, expected-value threshold, cooling-off period, kill switch check
- **Sub-modules:**
  - `position_math.py` — pure PnL / position-delta functions (no I/O, fully testable)
  - `fill_publisher.py` — `FillContext` dataclass + `publish_fill_events()`
  - `order_writer.py` — session-level DB write helpers
  - `decision_utils.py` — score parsing helpers (`_as_score()`)
- **Writes to:** `orders`, `positions`, `trade_performance`, `audit_log`

#### GradeAgent

- **Input:** `executions`, `trade_performance`, `trade_completed`
- **Output:** grade → `agent_grades`
- **Scoring formula:** `accuracy×0.35 + ic×0.30 + cost_eff×0.20 + latency×0.15`
- **Grade tiers:** A (≥0.8), B (≥0.6), C (≥0.4), D (≥0.2), F (<0.2)
- **Decision provenance:** records `model_used`, `primary_edge`, `decision_cost_usd` on every `trade_evaluations` row
- **Proposals:** after each fill, emits backtest-backed proposals (PARAMETER_CHANGE / PROMPT_EVOLUTION / TOOL_GOVERNANCE etc.)
- **Deterministic** — no LLM calls

#### ICUpdater

- **Input:** `trade_performance`
- **Output:** updated factor weights → `factor_ic_history`
- **Logic:** Spearman correlation between predicted direction and realized return; zeros out sub-threshold factors
- **Writes to:** `REDIS_KEY_IC_WEIGHTS` (25h TTL), `factor_ic_history` table
- **Trigger:** every `IC_UPDATE_EVERY_N_FILLS` fills
- **Deterministic** — no LLM calls

#### ReflectionAgent

- **Input:** `trade_performance`, `agent_grades`, `factor_ic_history`
- **Output:** reflection hypotheses → `reflection_outputs`
- **Logic:** LLM-powered pattern extraction over recent trade history; includes per-model performance summary so reflections can reason about *which model* is trading well
- **Read-only** — never writes orders
- **Trigger:** every `REFLECT_EVERY_N_FILLS` fills, minimum `REFLECTION_TRADE_THRESHOLD` trades in window

#### StrategyProposer

- **Input:** `reflection_outputs`
- **Output:** concrete proposals → `proposals`
- **Logic:** LLM ranks reflection hypotheses and drafts structured proposals:
  - `PARAMETER_CHANGE` — tune a gate/threshold
  - `PROMPT_EVOLUTION` — improve the adaptive directive
  - `TOOL_GOVERNANCE` — enable/disable a reasoning tool
  - `CODE_CHANGE` / `REGIME_ADJUSTMENT` — deferred to GitHub issue
  - `NEW_AGENT` — spawn a shadow challenger or file an issue

#### NotificationAgent

- **Input:** all key streams (`agent_logs`, `risk_alerts`, `proposals`, etc.)
- **Output:** formatted notifications → `notifications`
- **Logic:** classifies by severity (CRITICAL / URGENT / WARNING / INFO), deduplicates within 60s
- **Writes to:** `notifications:recent` (capped Redis list, max 200), `notifications` table

#### ChallengerAgent

- **Input:** `signals`, `trade_performance`
- **Logic:** shadow trades on alternative strategies (`mean_reversion`, `confirmed_trend`, `strong_only`) via `ShadowTradeEngine` — no real capital
- **Grading:** compares own strategy vs. baseline on realized moves; publishes `beats_baseline_shadow` evidence

#### ProposalApplier

- **Input:** `proposals`
- **Handler map:**

| Proposal type | Action |
|---|---|
| `PARAMETER_CHANGE` | Writes `config/param_overrides.json` on a dedicated branch via `GitOpsPublisher`; opens a PR for human review |
| `PROMPT_EVOLUTION` | Calls `PromptStore.set_directive()` — versioned, history-capped |
| `TOOL_GOVERNANCE` | Calls `ToolRegistry.set_enabled(name, False)` in-process |
| `NEW_AGENT` | Spawns via `ChallengerSpawner` if strategy in `backtest.strategies.STRATEGIES`; else files GitHub issue |
| `CODE_CHANGE` / `REGIME_ADJUSTMENT` | Files a GitHub issue for human design |

GitOps is gated on `GITHUB_TOKEN`. Dry-run locally if the token is absent.

### Canonical Agent Names

All agent names live in `api/constants.py` as SCREAMING_SNAKE_CASE constants. **Never write raw strings.**

| Constant | Value | Runtime identity |
|---|---|---|
| `AGENT_SIGNAL` | `"SIGNAL_AGENT"` | SignalGenerator |
| `AGENT_REASONING` | `"REASONING_AGENT"` | ReasoningAgent |
| `AGENT_EXECUTION` | `"EXECUTION_ENGINE"` | ExecutionEngine |
| `AGENT_GRADE` | `"GRADE_AGENT"` | GradeAgent |
| `AGENT_IC` | `"IC_UPDATER"` | ICUpdater |
| `AGENT_REFLECTION` | `"REFLECTION_AGENT"` | ReflectionAgent |
| `AGENT_STRATEGY` | `"STRATEGY_PROPOSER"` | StrategyProposer |
| `AGENT_NOTIFICATION` | `"NOTIFICATION_AGENT"` | NotificationAgent |
| `AGENT_CHALLENGER` | `"CHALLENGER_AGENT"` | ChallengerAgent |
| `AGENT_PROPOSAL` | `"PROPOSAL_APPLIER"` | ProposalApplier |

`ALL_AGENT_NAMES` is the ordered tuple of all 10. The frontend mirrors this in `frontend/src/constants/agents.ts`. `agentDisplayName()` is the only place a runtime constant becomes a UI label.

---

## 5. The Cognitive Brain (Deterministic Layer)

The `cognitive/` package is a separate, purely deterministic trading brain that runs alongside the agent pipeline. It has no LLM calls in its decision path — **all decisions are pure math**.

### Architecture

```
EventStream (in-memory, capped append-only log)
       │
       ├─ 5 Advisory Specialists (News, Technical, Macro, Risk, Reasoning)
       │    └─ produce SIGNAL events with numeric scores
       │
       ├─ Feature Aggregator
       │    └─ Σ signalᵢ·weightᵢ  →  composite_score
       │
       ├─ Deterministic Decision Engine
       │    └─ composite_score → BUY/SELL/HOLD
       │
       ├─ Hard Risk Gate (independent — never part of the score)
       │    └─ REJECT if risk feature crosses threshold
       │
       ├─ Execution (paper)
       │
       ├─ Attribution + Multi-Dimensional Grading
       │    └─ Direction×0.35 + Risk×0.30 + Execution×0.20 + Timing×0.15
       │
       ├─ LearningEngine (observations only — never edits config)
       │
       └─ ProposalAgent → shadow backtest gate → ChallengerAgent → GitOps PR
```

### Key Components

| Module | Purpose |
|---|---|
| `cognitive/cognitive.py` | `CognitiveLoop` — wires the full closed loop |
| `cognitive/decision.py` | Deterministic score → BUY/SELL/HOLD |
| `cognitive/risk.py` | Hard risk gate (independent of decision score) |
| `cognitive/grading.py` | Multi-dimensional grading (trades, agents, proposals, config versions) |
| `cognitive/trace.py` | Per-trade "why did we?" trace — pure read of the event stream |
| `cognitive/backtest_gate.py` | Paired shadow backtest (in/out split + walk-forward) |
| `cognitive/challenger.py` | Safety validator (sample size, overfit, risk impact, attribution) |
| `cognitive/governance.py` | `ProposalGovernor` — quota, dedup, reject cooldown |
| `cognitive/drift.py` | `DriftMonitor` — detects degradation in rolling quality windows |
| `cognitive/counterfactual.py` | Regret measurement per closed trade |
| `cognitive/gitops.py` | Branch + PR body generation (never auto-merges) |
| `cognitive/health.py` | Cognitive-wiring health (pure read) |
| `config/cognitive_config.json` | Git-versioned weights, thresholds, risk limits (data, not code) |

### Invariants

- **Constitution is immutable.** Risk feature is a hard gate, never part of the score — no combination of learned weights can override it.
- **No EXECUTION without a RISK_GATE.** Stream invariant enforced by the test `test_risk_independence_stream_invariant`.
- **Proposals require backtest evidence.** Every proposal must clear the `BacktestGate` (in/out split + walk-forward across ≥ 3 sequential windows; candidate must beat baseline in ≥60% of folds).
- **GitOps never auto-merges.** `cognitive/gitops.py` opens a PR; human reviews and merges.
- **Config lineage.** Every decision/execution/outcome event stamps `config_version` + `config_proposal_id` so the trace shows exactly which config version made each trade.

---

## 6. The Learning Loop

The full cycle: a tick arrives → a trade executes → the outcome is graded → patterns are extracted → a proposal is drafted → a human approves the PR → the next trade uses improved parameters.

```
PricePoller ── market_ticks ──▶ SignalGenerator ── signals ──▶ ReasoningAgent
                                                                      │
                                                              decisions (advisory)
                                                                      │
                                                               ExecutionEngine
                                    ┌─────────────────────────────────┤
                                    ▼              ▼                  ▼
                              executions    trade_performance    trade_lifecycle
                                    │              │
                    ┌───────────────┼──────────────┼───────────┐
                    ▼               ▼              ▼            ▼
               GradeAgent      ICUpdater   ChallengerAgent  NotificationAgent
                    │               │
              agent_grades  factor_ic_history
                    │               │
               ReflectionAgent ◀────┘
                    │
              reflection_outputs
                    │
               StrategyProposer ── proposals ──▶ ProposalApplier
                                                        │
                          ┌─────────────────────────────┤
                          ▼              ▼               ▼
                   signal_weight    PARAMETER_CHANGE  PROMPT_EVOLUTION
                   (Redis control)        │
                                  param-evolution-pr.yml
                                  (edits config/param_overrides.json)
                                         │
                                   GitHub PR ──▶ human review → merge
                                         │
                             api/constants.py reads override at startup
```

### Parameter Evolution (GitOps)

When the loop wants to tune a gate or threshold, `ProposalApplier` publishes a `pr_request`. The scheduled `param-evolution-pr.yml` GitHub Action:

1. Calls `GET /learning/pending-param-changes`
2. Edits `config/param_overrides.json` on a dedicated `param-evolution/<PARAMETER>` branch
3. Opens a PR for human review

On merge + restart, `api/constants.py` reads and re-validates the override against `PARAM_BOUNDS`. A bad or out-of-bounds value is ignored silently — no crash possible.

| Layer | File |
|---|---|
| Bounds validation | `api/services/param_evolution.py` |
| Override loader | `api/services/param_overrides.py` |
| Apply at import | `api/constants.py` (`ACTIVE_PARAM_OVERRIDES`) |
| PR runner script | `scripts/param_evolution_runner.py` |
| Workflow | `.github/workflows/param-evolution-pr.yml` |

---

## 7. Self-Evolving Directives

The ReasoningAgent's prompt has two layers:

1. **Constitution** — immutable. Defines hard safety and capital-preservation rules. Never modified by the learning loop.
2. **Adaptive directive** — the learned guidance assembled *beneath* the constitution. Written by `ProposalApplier` via `PromptStore.set_directive()` when a `PROMPT_EVOLUTION` proposal is approved or auto-applied.

`PromptStore` stores directives in Redis with full version history (capped at `PROMPT_DIRECTIVE_HISTORY_CAP`). When the reasoning agent assembles its next prompt, it calls `_get_adaptive_directive()` which reads the current directive. If absent, it falls back to the constitution-only prompt (never crashes).

**Invariant:** Because the adaptive directive is assembled beneath the constitution, safety guarantees cannot be weakened regardless of what the learning loop produces.

---

## 8. Decision Provenance

Every trade records which model made the decision and what it cost.

### Data Flow

1. `ReasoningAgent` stamps `model_used` (`provider:model`, e.g., `gemini:gemini-1.5-flash`) and `primary_edge` (the thesis) onto the decision.
2. `ExecutionEngine` carries `model_used` + `primary_edge` through `FillContext` to `trade_performance` and `trade_completed` events.
3. `GradeAgent` records both on each `trade_evaluations` row (migration `20260502_decision_provenance`).
4. `GET /learning/trades` returns `model_used` + `primary_edge`; the dashboard trade-detail modal shows the model and thesis behind every graded trade.
5. `GET /learning/model-performance` aggregates by `model_used`: trade count, win rate, avg score, total PnL, **LLM cost** (`decision_cost_usd`), and **net P&L = P&L − cost** — so you can compare which model earns the most money per dollar spent.
6. `ReflectionAgent` receives the per-model summary in its prompt, enabling reflections to reason about model-level performance, not just aggregate outcomes.

LM Studio (local) and free-tier providers have `decision_cost_usd = 0`, so net P&L equals P&L for them.

---

## 9. Storage Architecture

The system uses four storage layers with strict placement rules.

### Decision Flowchart

```
Is it a message flowing between agents?
  └─ YES → Redis Stream (STREAM_* constant)

Is it shared mutable state needing sub-millisecond reads?
  └─ YES → Redis KV (REDIS_KEY_* constant)
     └─ Must survive a Redis restart?
           YES → ALSO write to PostgreSQL (dual-write)
           NO  → Redis KV only

Is it a permanent record for audit/history?
  └─ YES → PostgreSQL
     └─ Could DB be down when written?
           YES → ALSO write to InMemoryStore as fallback
           NO  → PostgreSQL only

Is it transient UI data, no persistence needed?
  └─ YES → InMemoryStore.notifications (capped at 100, no DB write)
```

### Redis Streams — Event Bus

Used for agent-to-agent message passing only. Stream names are constants prefixed `STREAM_` in `api/constants.py`.

### Redis KV — Shared Mutable State

All keys are declared as constants in `api/constants.py`. Every key has a documented owner and TTL policy.

| Category | Constant | Key pattern | TTL | Owner |
|---|---|---|---|---|
| Market data | `REDIS_KEY_PRICES` | `prices:{symbol}` | **150s** (must exceed poll interval) | PricePoller |
| IC weights | `REDIS_KEY_IC_WEIGHTS` | `alpha:ic_weights` | 25h | ICUpdater |
| Prompt directive | `REDIS_KEY_PROMPT_DIRECTIVE` | `prompt:directive:{node}` | None | ProposalApplier |
| Kill switch | `REDIS_KEY_KILL_SWITCH` | `kill_switch:active` | None | RiskGuardian |
| Kill switch ts | `REDIS_KEY_KILL_SWITCH_UPDATED_AT` | `kill_switch:updated_at` | None | RiskGuardian |
| Paper cash | `REDIS_KEY_PAPER_CASH` | `paper:cash` | None | PaperBroker |
| Paper position | `REDIS_KEY_PAPER_POSITION` | `paper:positions:{symbol}` | None | PaperBroker |
| Order lock | `REDIS_KEY_ORDER_LOCK` | `order_lock:{symbol}` | **5s** | ExecutionEngine |
| Agent heartbeat | `REDIS_AGENT_STATUS_KEY` | `agent:status:{name}` | **5 min** | Each agent (via `write_heartbeat`) |
| Notifications list | `REDIS_KEY_NOTIFICATIONS_RECENT` | `notifications:recent` | None | NotificationAgent, ReasoningAgent |
| Decisions list | `REDIS_KEY_DECISIONS_RECENT` | `decisions:recent` | None | ReasoningAgent |
| LLM metrics | `REDIS_KEY_LLM_METRICS` | `llm:metrics` (hash) | None | LLMMetricsCollector |
| News sentiment | `REDIS_KEY_NEWS_SENTIMENT` | `news_sentiment:{symbol}` | 300s | market_intel |

**Critical Redis rules:**
- Hardcoded TTL values (`ex=30`) are an anti-pattern — always use named constants.
- Raw string keys are an anti-pattern — always use the `REDIS_KEY_*` constants.
- Agent heartbeats must go through `write_heartbeat()` (dual-writes Redis + Postgres) — never write directly.
- Kill switch absence = OFF. If Redis is unavailable during a kill-switch check, the check raises, routing the order to the DLQ (fail-closed, intentional).

### PostgreSQL — Durable Records

Used for everything that must survive a Redis restart.

See [Section 10](#10-database-schema-v3) for the full table reference.

### InMemoryStore — Postgres Substitute Only

`InMemoryStore` holds the same data shapes as Postgres tables when `is_db_available()` returns `False`. It is NOT a Redis alternative and has nothing to do with Redis.

| InMemoryStore field | Mirrors Postgres table |
|---|---|
| `agent_runs` | `agent_runs` |
| `agents` | `agent_heartbeats` (dashboard view) |
| `grade_history` | `agent_grades` |
| `event_history` | `events` |
| `vector_memory` | `vector_memory` |

`DEFAULT_AGENTS` keys in `InMemoryStore` must match the same SCREAMING_SNAKE_CASE constants that `write_heartbeat()` uses — otherwise ghost "idle" agents appear next to active agents in the dashboard.

---

## 10. Database Schema (v3)

### Key Tables

| Table | Purpose | PK type |
|---|---|---|
| `strategies` | Strategy definitions and configuration | UUID |
| `orders` | All orders with idempotency_key for dedup | UUID |
| `positions` | Current exposure per strategy/symbol | UUID |
| `trade_performance` | Trade outcomes (PnL, holding time, model attribution) | UUID |
| `trade_evaluations` | Graded trade records with decision provenance | UUID |
| `agent_runs` | Every agent execution with trace_id | **INTEGER** (sequence) |
| `agent_logs` | Step-level structured logs | UUID |
| `agent_grades` | GradeAgent scores | UUID |
| `agent_heartbeats` | Agent liveness history | UUID |
| `agent_pool` | Agent registry with hardcoded UUIDs | UUID |
| `events` | Append-only event ledger | **INTEGER** (sequence) |
| `vector_memory` | pgvector embeddings (1536-dim) for semantic memory | UUID |
| `factor_ic_history` | Alpha factor predictive performance over time | UUID |
| `audit_log` | Immutable change history | UUID |
| `trade_lifecycle` | Full trade state machine history | UUID |

### Critical Production Schema Realities

The live database was created before the Alembic migration system. Several tables have types and constraints that differ from what ORM models assume.

#### INTEGER Primary Keys (agent_runs, events)

```python
# CORRECT — never include id in INSERT; use RETURNING id
result = await session.execute(text("""
    INSERT INTO agent_runs (strategy_id, trace_id, source, schema_version, run_type)
    VALUES (:strategy_id, :trace_id, :source, :schema_version, :run_type)
    RETURNING id
"""), {...})
db_run_id = result.first()[0]  # integer from sequence

# Later UPDATE uses db_run_id (integer), NOT run_id (UUID)
await session.execute(text(
    "UPDATE agent_runs SET status='completed' WHERE id=:id"
), {"id": db_run_id})
```

#### Mandatory Columns Added by Migration 20260407

All INSERTs to these tables must include these columns:

| Table | Column | Type | Notes |
|---|---|---|---|
| `agent_runs` | `source` | VARCHAR(64) | writer identity (e.g., `AGENT_SIGNAL`) |
| `agent_runs` | `run_type` | VARCHAR(32) | defaults to `'analysis'` |
| `agent_runs` | `execution_time_ms` | INT | nullable; written in success UPDATE |
| `agent_logs` | `source` | VARCHAR(64) | writer identity |
| `agent_grades` | `source` | VARCHAR(64) | writer identity |
| `events` | `data` | JSONB | signal/event payload |
| `events` | `idempotency_key` | VARCHAR(255) + UNIQUE | dedup key |
| `events` | `schema_version` | VARCHAR(16) | always `'v3'` |

#### Correct Events INSERT (with dedup)

```sql
INSERT INTO events (event_type, entity_type, data, idempotency_key, source, schema_version)
VALUES ('signal.generated', 'signal', :data, :idem_key, :source, :schema_version)
ON CONFLICT (idempotency_key) DO NOTHING
```

---

## 11. LLM Integration

### Provider Routing

All LLM calls route through `api/services/llm_router.py`. The active provider is set by `LLM_PROVIDER` (default: `gemini`). `active_model_label()` returns the `provider:model` string used for decision provenance.

| Provider | Model env var | Default model |
|---|---|---|
| `gemini` **(default)** | `GEMINI_MODEL` | `gemini-1.5-flash` |
| `groq` | `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `anthropic` | `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` |
| `openai` | `OPENAI_MODEL` | `gpt-4o-mini` |
| `lmstudio` | `LM_STUDIO_MODEL` | `meta-llama-3.1-8b-instruct` |

### LLM Call Sites

| Call site | File | Prompt | Purpose |
|---|---|---|---|
| ReasoningAgent decision | `reasoning_agent.py:_call_llm` | `ADAPTIVE_TRADING_SYSTEM_PROMPT` | BUY/SELL/HOLD decision |
| ReasoningAgent self-critique | `reasoning_agent.py:_self_critique` | `REASONING_CRITIQUE_PROMPT` | Skeptical review of high-confidence decisions |
| ReflectionAgent | `pipeline_agents.py:_run_reflection` | `REFLECTION_SYSTEM_PROMPT` | Pattern + mistake analysis |
| StrategyProposer | `pipeline_agents.py:_plan_and_rank` | `STRATEGY_PLANNING_PROMPT` | Rank hypotheses and draft proposals |

GradeAgent and ICUpdater are **deterministic** — no LLM calls.

### Fallback Modes

`LLM_FALLBACK_MODE` controls what happens when the LLM provider is unavailable:

- `reject_signal` **(default)** — emit REJECT, never execute a naive buy. Safe.
- `skip_reasoning` — skip the reasoning step, allow downstream execution. Use with caution.

Provider throttle degrades to a smaller model in the same provider (not to a different provider). Budget exceed triggers REJECT.

### Local Inference (LM Studio)

LM Studio provides a local OpenAI-compatible HTTP server. Configure it as follows:

```env
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=127.0.0.1        # or Tailscale IP for remote GPU
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=meta-llama-3.1-8b-instruct
LM_STUDIO_TIMEOUT_SECONDS=90
```

When enabled, LM Studio is tried first on each LLM call; cloud provider is used as fallback. The `local_fallback_count` in `GET /llm/health` tracks how often fallback is triggered.

For Render (production) + home GPU, use LM Link (Tailscale):

```env
LM_STUDIO_HOST=100.64.x.x       # Tailscale IP of GPU machine
LM_LINK_ENABLED=true
LM_LINK_DEVICE_NAME=my-gpu-rig
```

Verify via:
```bash
curl -sS https://<backend>/api/llm/health | jq '{active_provider, lm_studio_healthy, local_latency_ms}'
```

### Token Budget and Cost Tracking

- Daily token cap: `ANTHROPIC_DAILY_TOKEN_BUDGET` (default 5,000,000 tokens)
- Cost alert threshold: `ANTHROPIC_COST_ALERT_USD`
- All LLM call outcomes are recorded via `LLMMetricsCollector` to the `llm:metrics` Redis hash and surfaced at `GET /llm/health`

---

## 12. Memory-Mode Resilience

When PostgreSQL is unavailable, `is_db_available()` returns `False` and all dashboard read paths short-circuit to `get_runtime_store()` before any SQL session is created.

### Rules

- **Never** create `AsyncSession`, `AsyncSessionFactory()`, or depend on `get_db` when `is_db_available()` is `False`.
- Dashboard endpoints return `source: "in_memory"` or `mode: "in_memory_fallback"` so data origin is transparent.
- The `/health` endpoint returns `database: "memory"` (not `"disconnected"`) in memory mode.
- `/readiness` is "ready" as long as Redis is up, regardless of DB status.

### Enabling Memory Mode

```env
USE_MEMORY_MODE=true
```

When set, the lifespan skips DB initialization entirely (no DNS retries). This is the recommended mode for development without a local Postgres instance.

### Redis-Backed REST Persistence

These REST endpoints work without Postgres because producers write to Redis lists/hashes:

| Endpoint | Redis key | Producer |
|---|---|---|
| `GET /notifications` | `notifications:recent` (cap 200) | NotificationAgent, ReasoningAgent |
| `GET /decisions` | `decisions:recent` (cap 500) | ReasoningAgent |
| `GET /llm/health` | `llm:metrics` hash | LLMMetricsCollector |

Writers must always go through `RedisStore.push_notification()` / `push_decision()` — these wrap LPUSH+LTRIM in a pipeline to prevent the cap being exceeded concurrently.

---

## 13. API Overview

The backend is a FastAPI application deployed on Render. All routes are prefixed `/api/`.

### Key Endpoints

#### Health and Readiness

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness — returns DB status, Redis status, schema version |
| `GET /readiness` | Readiness — fails only if Redis is down |

#### Dashboard Hydration

| Endpoint | Purpose |
|---|---|
| `GET /dashboard/state` | Full REST snapshot — orders, positions, agent logs, grades, proposals, trade feed, agent statuses, IC weights, prices |
| `WS /ws/dashboard` | WebSocket — real-time event broadcast |
| `GET /notifications` | REST catch-up for notifications (capped list) |
| `GET /decisions` | REST catch-up for decisions (capped list) |

#### Learning Pipeline

| Endpoint | Purpose |
|---|---|
| `GET /learning/trades` | Graded trade history with model provenance |
| `GET /learning/model-performance` | Per-model aggregates (win rate, avg score, PnL, cost, net P&L) |
| `GET /learning/reflections` | Reflection outputs |
| `GET /learning/strategies` | Strategy lifecycle |
| `GET /learning/pending-param-changes` | Pending parameter evolution proposals |

#### Agent and System Observability

| Endpoint | Purpose |
|---|---|
| `GET /dashboard/agents/status` | All agent statuses (heartbeat age → ACTIVE / STALE / OFFLINE) |
| `GET /system/trading-mode` | Current trading mode (PAPER / LIVE / UNKNOWN) |
| `GET /system/status` | Stream lag per consumer group |
| `GET /llm/health` | LLM provider health, cost metrics, local inference status |
| `GET /dashboard/tools` | Tool governance — registry, telemetry, alpha attribution |
| `GET /dashboard/prompt-evolution` | Active directive version and history |

#### Cognitive Brain (read-only)

| Endpoint | Purpose |
|---|---|
| `GET /cognitive/state` | Event stream snapshot |
| `GET /cognitive/events` | Recent events |
| `GET /cognitive/config` | Active cognitive config |
| `GET /cognitive/agents` | Specialist agent registry |
| `GET /cognitive/trace/{id}` | Per-trade trace with counterfactual and decisions |
| `POST /cognitive/reseed` | Reseed the cognitive config |

### WebSocket Message Types

The WebSocket at `/ws/dashboard` broadcasts:

- `agent_log` — agent activity event
- `notification` — buy/sell/alert notification
- `trade_lifecycle` — trade state change (fill, close, etc.)
- `market_event` — price tick from the poller
- `agent_grade` — grade computed by GradeAgent
- `agent_status` — heartbeat update

---

## 14. Frontend Dashboard

### Tech Stack

| Tool | Version | Purpose |
|---|---|---|
| Next.js | 14 (App Router) | Framework |
| TypeScript | strict mode | Type safety |
| Tailwind CSS | 3.x | Styling with Tone semantic tokens |
| Zustand | latest | Single-source-of-truth client state |
| Radix UI / shadcn | latest | Headless UI components |
| Recharts | latest | Charts |
| Vitest | latest | Unit and component tests |
| pnpm | 9.0.0 | Package manager |

### App Routes

| Route | Purpose |
|---|---|
| `/dashboard` | Main hub — hydrates all state on mount |
| `/dashboard/trading` | Trading tab — fills, positions, KPI stats |
| `/dashboard/agents` | Agent status, heartbeats, activity timeline |
| `/dashboard/learning` | Learning pipeline — grades, reflections, proposals |
| `/dashboard/proposals` | Proposal queue with approve/reject |
| `/dashboard/cognitive` | Cognitive brain Command Center |
| `/dashboard/system` | System health and stream diagnostics |

### State Management

All dashboard state lives in a single Zustand store (`useCodexStore`). The single-write-path rule: every collection has exactly one normalizing write action.

| Store action | Collection | Trigger |
|---|---|---|
| `addNotification(raw)` | `notifications[]` | WebSocket `notification` message or REST catch-up |
| `addTradeFeedItem(item)` | `tradeFeed[]` | WebSocket `trade_lifecycle` message |
| `setTradeFeed(raw[])` | `tradeFeed[]` | REST snapshot hydration |
| `hydrateDashboard(data)` | all collections | REST `GET /dashboard/state` on mount + reconnect |

### Data Flow

```
Backend (FastAPI)
  │
  ├─ WebSocket (/ws/dashboard)
  │    └─ useGlobalWebSocket → store write actions
  │
  ├─ REST snapshot (GET /dashboard/state, polled on mount + every reconnect)
  │    └─ hydrateDashboard() → bulk merge into store
  │
  └─ REST catch-up (GET /notifications, /decisions — replayed on reconnect)
       └─ addNotification() / addDecision() per item
```

WebSocket reconnect automatically re-triggers both REST catch-ups so the dashboard self-heals after network interruptions.

### Design System

All colors go through semantic **Tone tokens** defined in `tailwind.config.js` and `frontend/src/styles/globals.css`. Never use hardcoded hex or Tailwind color classes directly — always use the semantic aliases:

```tsx
// ❌ Wrong
<div className="text-green-500">

// ✅ Right
<div className="text-tone-success">
```

### Persistence Banner

When `dashboardData.degraded_mode` is `true` (DB unavailable), `DashboardView` renders an amber warning banner. `degraded_reason` provides the machine-readable cause (`"db_unavailable"` | `"redis_unavailable"`).

### Notification Grouping

`NotificationFeed` collapses semantically identical notifications (same `notification_type + symbol + action`) into a single card with a count badge. This prevents repeated BUY/SELL signals from flooding the feed during high-frequency sessions. Logic lives in `src/lib/notification-grouping.ts` (pure, tested).

### Agent Activity Freshness

`deriveActivityIndicator` (in `src/lib/agent-activity.ts`) maps a timestamp + connection state to `'live' | 'waiting' | 'offline'`. Uses `agentLogs[0]?.timestamp` (newest entry — store prepends) for freshness, not the display-window tail.

---

## 15. Development Guide

### Prerequisites

- Python 3.10+
- Node.js 20+
- PostgreSQL 15+ with the `pgvector` extension (or use `USE_MEMORY_MODE=true` to skip)
- Redis 5.0+
- pnpm 9.0.0 (`npm install -g pnpm@9`)

### Install

```bash
git clone https://github.com/SamuelMatthew95/trading-control.git
cd trading-control

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && pnpm install
```

### Configure

```bash
cp .env.example .env
```

Minimum required variables:

```env
# Skip DB in development (recommended for quick local start)
USE_MEMORY_MODE=true

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM (Gemini is default; get a free API key at aistudio.google.com)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key

# Alpaca (paper trading only in development)
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true
```

### Run

```bash
# Backend API (port 8000)
uvicorn api.main:app --reload

# Frontend dashboard (port 3000, separate terminal)
cd frontend && pnpm dev

# Verify backend is up
curl http://localhost:8000/api/health | jq .
```

### Lint and Format

```bash
ruff check . --fix          # fix all lint issues
ruff format .               # format
ruff format --check .       # verify formatting (for CI check)
ruff check . --select=E9,F63,F7,F82  # critical error check
```

### Test Commands (mirrors CI exactly)

```bash
# Run in this order, separately:
pytest tests/core tests/api -v --tb=short    # unit tests (CI step 1)
pytest tests/integration -v --tb=short       # integration tests (CI step 2)
pytest tests/agents -v --tb=short            # agent tests (local only, not in CI)
```

**Never run `pytest tests/` as a single combined command** — CI runs two separate subsets, and ordering-sensitive failures only surface when you run them split.

### Adding a New Agent

1. Create `api/services/agents/your_agent.py` using the template in `docs/AGENTS.md`.
2. Add a row to the `agent_pool` seed migration with a hardcoded UUID.
3. Add `AGENT_YOUR_NAME` constant to `api/constants.py` and include it in `ALL_AGENT_NAMES`.
4. Mirror the constant in `frontend/src/constants/agents.ts`.
5. Register the agent in `api/main.py`.
6. Add tests in `tests/agents/test_your_agent.py`.
7. Update the stream chain table in `docs/architecture.md`.
8. Add a row to the agent table in `docs/AGENTS.md`.
9. Update `CHANGELOG.md`.

### Adding a New API Endpoint

1. Create or update a route file in `api/routes/`.
2. If the endpoint reads dashboard/metrics data, add the memory-mode guard:
   - Check `is_db_available()` before creating any session.
   - Return from `get_runtime_store()` with `source: "in_memory"` when DB is unavailable.
   - Add a regression test that verifies the DB session factory is not called in memory mode.
3. Register the router in `api/main.py`.
4. Add tests in `tests/api/test_{router_name}.py`.
5. If the file is new, add it to `CLEAN_FILES` in `tests/core/test_field_name_guardrails.py`.
6. Update `CHANGELOG.md`.

### Coding Standards

- **Imports:** All imports at file top. Inline imports only for circular-import breaks or optional deps — always add `# noqa: PLC0415`.
- **Logging:** Always use `log_structured()`. Never `print()` or `logger.*`. Always `exc_info=True` on error logs.
- **Dict keys:** All event/payload dict keys must go through `FieldName` enum — never raw strings.
- **Redis keys:** Only use `REDIS_KEY_*` constants — never hardcoded strings.
- **Agent names:** Only use `AGENT_*` constants — never raw strings.
- **DB writes:** Always through `SafeWriter` — never raw `session.execute(INSERT ...)` except for `agent_runs`/`events` INTEGER PK tables.
- **FastAPI dependencies:** Use `Annotated[Type, Depends(...)]` syntax, not default-argument `Depends(...)`.
- **Exception chaining:** `raise HTTPException(...) from None` inside `except` blocks.

---

## 16. Deployment Guide

### Backend (Render)

**Start command:**
```
gunicorn api.main:app -k uvicorn.workers.UvicornWorker
```

**Required environment variables:**

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/trading_control
REDIS_URL=redis://host:6379/0

# LLM
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key
GROQ_API_KEY=your_groq_key          # optional fallback
ANTHROPIC_API_KEY=your_key          # optional fallback

# Alpaca
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true
MARKET_DATA_PROVIDER=alpaca

# App
FRONTEND_URL=https://trading-control-khaki.vercel.app
BROKER_MODE=paper
LOG_LEVEL=INFO
ENABLE_SIGNAL_SCHEDULER=true

# Agent thresholds
SIGNAL_EVERY_N_TICKS=10
GRADE_EVERY_N_FILLS=5
IC_UPDATE_EVERY_N_FILLS=10
REFLECT_EVERY_N_FILLS=10
REFLECTION_TRADE_THRESHOLD=20

# LLM limits
LLM_TIMEOUT_SECONDS=15
LLM_MAX_RETRIES=2
LLM_FALLBACK_MODE=reject_signal
ANTHROPIC_DAILY_TOKEN_BUDGET=5000000
ANTHROPIC_COST_ALERT_USD=5.0
```

**Backend deployment checklist:**
1. Provision PostgreSQL 15+ and enable the `pgvector` extension.
2. Provision Redis 5.0+.
3. Set all required environment variables.
4. Deploy — the lifespan handler runs DB connectivity check + schema initialization automatically.
5. Run smoke checks (see below).

### Frontend (Vercel)

1. Connect the `frontend/` directory to Vercel.
2. Set `NEXT_PUBLIC_API_URL` to the Render backend URL.
3. Ensure Render's `FRONTEND_URL` allows the Vercel origin (CORS).
4. Verify the dashboard loads at `/dashboard`.

### Database Migrations

Schema is initialized automatically on startup. For manual migration:

```bash
alembic upgrade head
```

Verify schema version:
```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs WHERE schema_version='v3';"
```

### Post-Deploy Smoke Checks

```bash
# Backend health
curl -sS https://<backend>/api/health | jq .

# Dashboard hydration (must return JSON even in memory mode)
curl -sS https://<backend>/api/dashboard/state | jq '.source // .mode'

# Agent statuses
curl -sS https://<backend>/api/dashboard/agents/status | jq .

# Stream health (check for consumer lag)
curl -sS https://<backend>/api/system/status | jq .

# LLM health
curl -sS https://<backend>/api/llm/health | jq '{active_provider, lm_studio_healthy}'

# Redis stream verification
redis-cli -u $REDIS_URL xlen market_ticks   # > 0 within 30s of poller starting
redis-cli -u $REDIS_URL xlen signals        # > 0 shortly after
redis-cli -u $REDIS_URL xlen decisions      # > 0 shortly after
redis-cli -u $REDIS_URL keys "agent:status:*"
```

---

## 17. Testing Guide

### Test Structure

```
tests/
├── core/                         # Foundation guardrail tests (in CI)
│   ├── conftest.py               # autouse InMemoryStore + db_available reset
│   ├── fake_session.py           # FakeAsyncSession for DB mocking
│   ├── test_production_schema_guardrails.py   # source-code schema inspection
│   ├── test_field_name_guardrails.py          # FieldName enum CI enforcement (AST scan)
│   ├── test_agent_constants.py               # Agent name + InMemoryStore key consistency
│   ├── test_data_fetch_guardrails.py
│   ├── test_cognitive_*.py
│   └── ...
├── api/                          # API endpoint tests (in CI)
│   ├── test_health_memory_mode.py
│   ├── test_learning_routes.py
│   ├── test_decisions_routes.py
│   ├── test_notifications_routes.py
│   ├── test_websocket_fixes.py
│   └── ...
├── agents/                       # Per-agent tests (local only — NOT in CI)
│   ├── test_signal_generator*.py (3 files)
│   ├── test_reasoning_agent.py
│   ├── test_execution_engine*.py (3 files)
│   ├── test_position_math.py     # 35 pure-function unit tests
│   ├── test_grade_agent.py
│   └── ...
└── integration/                  # End-to-end pipeline tests (in CI)
```

### Test Isolation (Critical)

`_db_available` and `get_runtime_store()` are module-level globals. The `conftest.py` autouse fixture resets both before every test:

```python
@pytest.fixture(autouse=True)
def _reset_runtime_state():
    set_runtime_store(InMemoryStore())
    set_db_available(False)
```

Rules:
- Never call `set_db_available(True)` globally — use `monkeypatch.setattr(module, "is_db_available", lambda: True)` instead.
- Never assume the store is empty; the autouse fixture guarantees it.

### Mocking Patterns

#### Database

```python
from tests.core.fake_session import FakeAsyncSession

async def test_example(fake_session: FakeAsyncSession):
    writer = SafeWriter(fake_session)
    record_id = await writer.write(table="orders", data={...}, schema_version="v3", source="test")
    assert record_id is not None
```

#### Redis

```python
import pytest_asyncio
import fakeredis

@pytest_asyncio.fixture
async def redis():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield r
    await r.aclose()
```

**Important:** Use positional args with `xgroup_create` (keyword `id=` breaks FakeRedis):
```python
await redis.xgroup_create(stream, group, "$", mkstream=True)  # correct
await redis.xgroup_create(stream, group, id="$", mkstream=True)  # breaks
```

#### Memory-Mode Dashboard Tests

Every dashboard endpoint must have a test proving it does not call the DB session factory in memory mode:

```python
factory_calls = []

def recording_factory():
    factory_calls.append("called")
    raise AssertionError("should not be called in memory mode")

monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", recording_factory)
set_db_available(False)

payload = await dashboard_v2.get_dashboard_state()

assert payload["source"] == "in_memory"
assert factory_calls == []
```

### CI Pipeline

CI runs on Python 3.10 and 3.11 in parallel:

```bash
# Step 1 — Lint
ruff check . --fix
ruff format --check .
ruff check . --select=E9,F63,F7,F82

# Step 2 — Unit tests
pytest tests/core tests/api -v

# Step 3 — Integration tests
pytest tests/integration -v
```

`tests/agents/` is local-only — run it before pushing to catch agent regressions.

---

## 18. Key Guardrails and Conventions

### FieldName Enum (CI-Enforced)

All event, payload, and DB-row dict access must go through the `FieldName` StrEnum (~720 members) in `api/constants.py`. Raw string keys silently break when payload fields are renamed.

```python
from api.constants import FieldName

# ❌ Wrong
side = data.get("side")
payload = {"symbol": s, "trace_id": tid}

# ✅ Right
side = data.get(FieldName.SIDE)
payload = {FieldName.SYMBOL: s, FieldName.TRACE_ID: tid}
```

`tests/core/test_field_name_guardrails.py` runs an AST scan and hard-fails CI if any file on `CLEAN_FILES` re-introduces a raw FieldName string key. The list can only grow — removing a file is a regression.

When you add a new `api/` file, sweep it of raw strings and add it to `CLEAN_FILES`.

### Redis Key Constants

All Redis keys are defined in `api/constants.py`. Never use raw string keys.

```python
# ❌ Wrong
await redis.get("kill_switch:active")

# ✅ Right
await redis.get(REDIS_KEY_KILL_SWITCH)
```

### Agent Name Constants

Never write agent name strings inline.

```python
# ❌ Wrong
await redis.set("agent:status:SIGNAL_AGENT", ...)

# ✅ Right
await redis.set(REDIS_AGENT_STATUS_KEY.format(name=AGENT_SIGNAL), ...)
```

### Test Isolation

Never call `set_db_available(True)` globally in a test — use `monkeypatch` on the specific module under test. Global `set_db_available(True)` leaks into subsequent tests and causes ghost-state failures.

### Inline Import Rule (ruff PLC0415)

All imports must be at the top of the file. Inline imports are only permitted for:
- Circular-import breaks
- Optional/lazy dependencies

Each must carry `# noqa: PLC0415`.

### Schema Version

Every new database INSERT must include `schema_version='v3'`.

### Heartbeat Dual-Write

Always use `write_heartbeat()` from `api/services/agent_heartbeat.py` — never write directly to the Redis heartbeat key. The function writes to both Redis (with TTL) and the Postgres `agent_heartbeats` table.

### CRITICAL Timing Invariant

`AGENT_HEARTBEAT_TTL_SECONDS` (300s) must always be greater than `AGENT_STALE_THRESHOLD_SECONDS` (120s). If the TTL is shorter than the stale threshold, a slow-but-running agent expires before the dashboard can ever mark it as STALE — it goes straight to "offline."

---

## 19. Configuration Reference

Key environment variables (see `.env.example` for the complete list):

### Infrastructure

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | required | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `REDIS_URL` | required | Redis URL |
| `USE_MEMORY_MODE` | `false` | Skip DB entirely; dashboard uses InMemoryStore |
| `FRONTEND_URL` | `http://localhost:3000` | Allowed CORS origin |

### LLM

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Active LLM provider (`gemini`, `groq`, `anthropic`, `openai`, `lmstudio`) |
| `GEMINI_API_KEY` | — | Gemini API key |
| `GROQ_API_KEY` | — | Groq API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model |
| `LLM_TIMEOUT_SECONDS` | `15` | LLM call timeout |
| `LLM_MAX_RETRIES` | `2` | Max retries on transient errors |
| `LLM_FALLBACK_MODE` | `reject_signal` | Fallback when LLM unavailable |
| `ANTHROPIC_DAILY_TOKEN_BUDGET` | `5000000` | Daily token cap |

### Local Inference (LM Studio)

| Variable | Default | Description |
|---|---|---|
| `LM_STUDIO_ENABLED` | `false` | Enable LM Studio |
| `LM_STUDIO_HOST` | `127.0.0.1` | LM Studio host |
| `LM_STUDIO_PORT` | `1234` | LM Studio port |
| `LM_STUDIO_MODEL` | `meta-llama-3.1-8b-instruct` | Model to use |
| `LM_STUDIO_TIMEOUT_SECONDS` | `90` | Inference timeout |
| `LM_LINK_ENABLED` | `false` | Flag for remote GPU via Tailscale |

### Alpaca (Broker)

| Variable | Default | Description |
|---|---|---|
| `ALPACA_API_KEY` | required | Alpaca API key |
| `ALPACA_SECRET_KEY` | required | Alpaca secret key |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | Always paper in development |
| `ALPACA_PAPER` | `true` | Paper trading flag |
| `BROKER_MODE` | `paper` | `paper` or `live` |

### Agent Thresholds

| Variable | Default | Description |
|---|---|---|
| `SIGNAL_EVERY_N_TICKS` | `10` | Signal generation frequency |
| `GRADE_EVERY_N_FILLS` | `5` | Grade computation frequency |
| `IC_UPDATE_EVERY_N_FILLS` | `10` | IC weight update frequency |
| `REFLECT_EVERY_N_FILLS` | `10` | Reflection frequency |
| `REFLECTION_TRADE_THRESHOLD` | `20` | Min trades required before reflection |
| `REASONING_COOLDOWN_SECONDS` | `60` | Cooldown between reasoning calls for same symbol |
| `REASONING_SELF_CRITIQUE_ENABLED` | `false` | Enable skeptical self-critique pass |
| `SIGNAL_CONFIDENCE_MIN_GATE` | `0.50` | Min confidence score to pass to execution |

### Prompt Evolution

| Variable | Default | Description |
|---|---|---|
| `PROMPT_EVOLUTION_ENABLED` | `false` | Allow proposals to evolve the directive |
| `PROMPT_EVOLUTION_AUTO_APPLY` | `false` | Auto-apply without human approval |

---

## 20. Troubleshooting Quick Reference

The `docs/troubleshooting/` directory contains per-subsystem incident guides. Each entry has: **Symptom → Root cause → Fix → Regression test**.

| Guide | Covers |
|---|---|
| `notifications.md` | Buy/sell pipeline, WebSocket delivery, dedup |
| `execution-engine.md` | Score parsing, fill publishing, backlog, decisions counter |
| `data-consistency.md` | PnL / win rate / positions across DB + memory paths |
| `system-routes.md` | Stream lag endpoint, trading-mode status, memory-mode guards |
| `ci-cd.md` | Lint failures, ruff version pinning, GitHub Actions |
| `frontend.md` | Dashboard UI bugs: stat tiles, P&L display, win-rate fallback |
| `lm-studio.md` | Local inference: startup, timeout, fallback, secrets |
| `backtest.md` | Strategy comparison: eligibility gates, "NO SIGNALS" vs 0.00 |
| `signal-generation.md` | Volatility-normalized thresholds, idle-bot / "no signals" |
| `market-intel.md` | Perception tools: order-book, news, correlation failures |
| `tailscale.md` | SOCKS5 vs HTTP-CONNECT, peerAPI diagnosis |
| `agents.md` | Fleet lifecycle: supervision, crash detection, restart |
| `cognitive.md` | Cognitive brain: event loop, deterministic decision, walk-forward, governance |
| `proposals.md` | Proposal creation guardrails, read path, queue ingestion |

### Most Common Root Causes

| Symptom | Most likely cause |
|---|---|
| All decisions are HOLD | `pct` pinned to 0 — price poller lost its prev-price anchor (check Redis TTL vs poll interval) |
| Agents show OFFLINE | Heartbeat TTL shorter than the stale threshold, or `DEFAULT_AGENTS` keys don't match `ALL_AGENT_NAMES` |
| Dashboard blank in memory mode | Endpoint creating `AsyncSessionFactory()` before `is_db_available()` check |
| Stream lag grows without bound | Agents sharing one consumer group (`workers`) instead of per-agent groups |
| `"Consumer group not found"` in `/system/status` | Hardcoded `"trading_workers"` instead of `DEFAULT_GROUP` constant |
| CI fails with import error | New `api/` file not added to `CLEAN_FILES` in `test_field_name_guardrails.py` |
| `pytest tests/` passes but CI fails | Running combined suite instead of split (`tests/core tests/api` then `tests/integration`) |
| FieldName guardrail CI failure | Raw string dict key re-introduced in a CLEAN_FILES file |
| `Task was destroyed but pending` | Fire-and-forget `asyncio.create_task()` not held in a strong-reference set |

---

*Last updated: 2026-06-05. Reflects schema v3, cognitive brain (counterfactuals + walk-forward + drift detection), decision provenance (model_used + net P&L), and the GitOps parameter evolution loop.*
