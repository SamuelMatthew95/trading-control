# Architecture

## High-level system

`trading-control` is a modular FastAPI backend that coordinates a planner/executor/evaluator multi-agent workflow.

```text
api/
├── main.py                # App wiring, middleware, router registration, startup
├── database.py            # Async engine/session + health checks/init
├── config.py              # Settings + env validation
├── core/models.py         # API and DB models
├── routes/                # HTTP surface area
│   ├── health.py
│   ├── analyze.py
│   ├── trades.py
│   └── performance.py
└── services/              # Business services used by routes
    ├── trading.py
    ├── learning.py
    └── memory.py

multi_agent_orchestrator.py # Planner + execution + evaluation runtime
```

## Request flow

1. A route receives a request (`/api/analyze`, `/api/trades`, etc.).
2. The route pulls shared services from `api.main_state`.
3. Service code invokes the orchestrator and/or DB-backed models.
4. Results are returned as typed API responses.

## Startup and runtime behavior

On startup (`api.main`):

- validates DB connectivity,
- initializes DB schema,
- creates the orchestrator,
- registers shared services (`TradingService`, `AgentLearningService`, `AgentMemoryService`).

Global error handling is centralized in `api.main` with a JSON error response shape.

## Agent orchestration

The orchestrator (`multi_agent_orchestrator.py`) is organized around:

- planning,
- tool-mediated execution with guardrails/retries,
- evaluation and confidence handling,
- shadow-mode style analysis workflows.

This keeps decisioning behavior isolated from HTTP concerns.
