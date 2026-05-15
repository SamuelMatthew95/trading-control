# Architecture

## System Overview

Trading Control is an event-driven algorithmic trading platform built around a 7-agent AI pipeline. Agents communicate exclusively through Redis Streams — never by calling each other directly.

```
Runtime Store (memory-first when DB is down)
        │
        ▼
  Redis Streams (event delivery / fan-out)
        │
        ▼
  AI Agents (consumers)
        │
        ▼
  PostgreSQL (durable persistence when available)
        │
        ▼
  Next.js Dashboard (REST + WebSocket hydration)
```

## Runtime Storage Contract

The dashboard must stay usable when PostgreSQL is unavailable. `api.runtime_state.is_db_available()` is the routing switch:

- `False`: read dashboard state from `get_runtime_store()` only. Do not create an `AsyncSession`, do not call `AsyncSessionFactory()`, and do not depend on `get_db`.
- `True`: read durable history from PostgreSQL and use in-memory data only as a compatibility fallback.
- Every memory-mode dashboard payload should include `source: "in_memory"` or `mode: "in_memory"` so the UI and logs make the data source obvious.

This applies to `api/routes/dashboard_v2.py`, `api/routes/ws.py`, and `api/services/metrics_aggregator.py`. The in-memory store is not a secondary afterthought for dashboard hydration; it is the primary runtime source whenever DB health is false.

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
ExecutionEngine     → executions / trade_performance / trade_lifecycle
     │
     ▼
GradeAgent          → agent_grades
     │
     ├── ICUpdater          → factor_ic_history
     ├── ReflectionAgent    → reflection_outputs
     ├── StrategyProposer   → proposals
     └── NotificationAgent  → notifications
```

### Stream chain

| Stream | Producer | Consumer(s) |
|---|---|---|
| `market_ticks` | Price poller (Alpaca) | SignalGenerator |
| `market_events` | Price poller (Alpaca) | Dashboard/WS |
| `signals` | SignalGenerator | ReasoningAgent |
| `decisions` | ReasoningAgent, RiskGuardian | ExecutionEngine |
| `executions` | ExecutionEngine | GradeAgent, ICUpdater, NotificationAgent |
| `trade_performance` | ExecutionEngine | GradeAgent, ICUpdater, ReflectionAgent |
| `trade_completed` | ExecutionEngine (round-trips only) | GradeAgent |
| `trade_lifecycle` | ExecutionEngine | Dashboard/WS |
| `agent_grades` | GradeAgent | Dashboard |
| `factor_ic_history` | ICUpdater | ReflectionAgent |
| `reflection_outputs` | ReflectionAgent | StrategyProposer |
| `proposals` | StrategyProposer | NotificationAgent |
| `notifications` | NotificationAgent | Dashboard/WS |
| `risk_alerts` | RiskGuardian, AgentSupervisor | NotificationAgent |
| `agent_logs` | All agents | NotificationAgent |
| `dlq` | DLQManager | DLQManager (retry) |

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

### Notification contract

Notification payloads consumed by the dashboard should be UI-ready and deterministic. The backend decides whether a notification is displayable and emits a stable id for dedup across REST hydration, websocket live updates, and page reloads.

Required display keys:
- `id` (stable deterministic id)
- `severity` (`success` | `info` | `warning` | `critical`)
- `title`
- `body` (English fallback)
- `icon`
- `timestamp` (ISO8601)
- `metadata` (raw typed values already chosen by backend for direct rendering)

The frontend should render this payload directly and should not apply business filtering, enrichment, or localization logic.

Operational guardrails:
- Notifications stream writes must be bounded with Redis `MAXLEN` trimming to prevent unbounded growth.
- If notification DB persistence fails but live broadcast succeeds, emit an explicit warning log including `notification_id` and `trace_id` so hydration gaps are observable.

Dashboard hydration API should also include `notification_summary` computed by backend:
- `summary_version`
- `counts`: `total`, `open`, `resolved`
- `severity_counts`: ordered list of `{ severity, count }`
- Backward-compatible fields: `total`, `open`, `resolved`, `by_severity`
This removes counting/filtering logic from the UI and keeps rendering deterministic.


## Repository structure

```
api/
├── main.py                      # App wiring, middleware, router registration, startup
├── database.py                  # Async engine, session factory, health checks
├── config.py                    # Pydantic settings — all env vars live here
├── constants.py                 # ALL Redis keys, TTLs, agent names, FieldName enum
├── observability.py             # log_structured() — the only logging function to use
├── runtime_state.py             # is_db_available() routing switch + InMemoryStore
├── schema_version.py            # DB_SCHEMA_VERSION constant ("v3")
├── events/
│   └── bus.py                   # Redis Streams EventBus — DEFAULT_GROUP = "workers"
├── routes/                      # HTTP route modules (one file per feature)
│   ├── health.py
│   ├── system.py                # /system/* observability + SSE log stream
│   ├── dashboard_v2.py
│   ├── ws.py
│   └── ...
├── services/
│   ├── agent_heartbeat.py       # Shared heartbeat writer (Redis + Postgres)
│   ├── redis_store.py           # RedisStore — notifications/decisions/llm_metrics lists
│   ├── metrics_aggregator.py    # DB/memory snapshot for dashboard hydration
│   └── execution/
│       ├── execution_engine.py  # Orchestrator — process() delegates to sub-modules
│       ├── position_math.py     # Pure PnL / position-delta functions (no IO)
│       ├── fill_publisher.py    # FillContext dataclass + publish_fill_events()
│       ├── order_writer.py      # Session-level DB write helpers (insert/update/upsert)
│       └── decision_utils.py    # extract_decision_scores(), _as_score() helpers
└── core/
    └── models.py                # SQLAlchemy ORM models (Order, Position, SystemMetrics, …)
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
| **Determinism** | All writes through `SafeWriter` only; pipeline selects an explicit route (DB/MEMORY/SKIP) via `determine_persist_route` before attempting any write |
| **Idempotency** | `idempotency_key` on orders and events |
| **Traceability** | `trace_id` spans event → agent_run → agent_log → vector_memory |
| **Replayability** | Full state rebuildable from the `events` table |
| **Atomicity** | Business write + event emit succeed or fail together |
| **DB outage tolerance** | Dashboard reads short-circuit to `get_runtime_store()` before SQL session creation |

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
