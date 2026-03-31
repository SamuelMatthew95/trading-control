# Architecture

## System Overview

Trading Control is an event-driven algorithmic trading platform built around a 7-agent AI pipeline. Agents communicate exclusively through Redis Streams — never by calling each other directly.

```
PostgreSQL (Source of Truth)
        │
        ▼
  Redis Streams (Event delivery / fan-out)
        │
        ▼
  AI Agents (Consumers — never modify source truth directly)
        │
        ▼
  Next.js Dashboard (Real-time via SSE + WebSocket)
```

## Agent Pipeline

```
market_ticks
     │
     ▼
SignalGenerator     → signals
     │
     ▼
ReasoningAgent      → decisions
     │
     ▼
GradeAgent          → agent_grades
     │
     ├── ICUpdater          → ic_weights
     ├── ReflectionAgent    → reflection_outputs
     ├── StrategyProposer   → proposals
     └── NotificationAgent  → notifications
```

### Stream chain

| Stream | Producer | Consumer(s) |
|---|---|---|
| `market_ticks` | Price poller (Alpaca) | SignalGenerator |
| `signals` | SignalGenerator | ReasoningAgent |
| `decisions` | ReasoningAgent | GradeAgent |
| `graded_decisions` | GradeAgent | ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent |

### Agent responsibilities

| Agent | Purpose |
|---|---|
| **SignalGenerator** | Converts raw ticks to typed signals (STRONG_MOMENTUM ≥3%, MOMENTUM ≥1.5%, PRICE_UPDATE otherwise) |
| **ReasoningAgent** | LLM-powered trade decision with token budget, fallback modes, and vector memory search |
| **GradeAgent** | Scores agents across 4 dimensions: accuracy×0.35 + ic×0.30 + cost_eff×0.20 + latency×0.15 |
| **ICUpdater** | Reweights alpha factors using Spearman correlation, zeros out sub-threshold factors |
| **ReflectionAgent** | Finds patterns in recent trades and generates hypotheses (read-only, never writes orders) |
| **StrategyProposer** | Converts reflection hypotheses into concrete proposals requiring explicit approval |
| **NotificationAgent** | Classifies events by severity (CRITICAL/URGENT/WARNING/INFO) and deduplicates within 60s |

## Repository structure

```
api/
├── main.py                      # App wiring, middleware, router registration, startup
├── database.py                  # Async engine, session factory, health checks
├── config.py                    # Pydantic settings — all env vars live here
├── observability.py             # log_structured() — the only logging function to use
├── events/
│   └── bus.py                   # Redis Streams EventBus (xread, xadd, xgroup_create)
├── routes/                      # 13 HTTP route modules (one file per feature)
│   ├── health.py
│   ├── analyze.py
│   ├── trades.py
│   ├── performance.py
│   ├── dashboard.py
│   ├── feedback.py
│   ├── monitoring.py
│   ├── system.py
│   ├── system_health.py
│   ├── dlq.py
│   └── ws.py
├── services/
│   └── agents/
│       ├── pipeline_agents.py   # GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent
│       └── reasoning_agent.py   # LLM-powered ReasoningAgent
└── core/
    ├── db/                      # Session management, migrations
    └── writer/
        └── safe_writer.py       # The ONLY authorized write path to the database
```

## Request flow

1. A route receives an HTTP request.
2. The route pulls shared services from `api.main_state`.
3. Service code reads from DB or publishes to Redis Streams.
4. Results are returned as typed Pydantic responses.
5. Stream consumers (agents) process events asynchronously.

## Startup sequence

On startup (`api.main`):

1. Validates DB connectivity and schema version.
2. Initializes DB schema (creates tables if missing).
3. Creates the `EventBus` and connects to Redis.
4. Registers shared services (`TradingService`, `AgentLearningService`, `AgentMemoryService`).
5. Agents begin their XREAD loops and write WAITING status to Redis.

## System guarantees

| Guarantee | Mechanism |
|---|---|
| **Determinism** | All writes through `SafeWriter` only |
| **Idempotency** | `idempotency_key` on orders and events |
| **Traceability** | `trace_id` spans event → agent_run → agent_log → vector_memory |
| **Replayability** | Full state rebuildable from the `events` table |
| **Atomicity** | Business write + event emit succeed or fail together |

## Database schema (v3)

Key tables:

| Table | Purpose |
|---|---|
| `strategies` | Strategy definitions and configuration |
| `orders` | All orders with idempotency_key for dedup |
| `positions` | Current exposure per strategy/symbol |
| `trade_performance` | Trade outcomes (PnL, holding time, attribution) |
| `agent_runs` | Every agent execution with trace_id |
| `agent_logs` | Step-level structured logs |
| `vector_memory` | pgvector embeddings (1536-dim) for semantic memory |
| `factor_ic_history` | Alpha factor predictive performance over time |
| `audit_log` | Immutable change history |

Schema version: **v3**. Always use `schema_version='v3'` on new inserts.
