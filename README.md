# Trading Control

Production-oriented multi-agent trading control system with a modular FastAPI backend, planner/executor agent orchestration, guardrailed tools, and evaluation-focused workflows.

## Overview

This repository provides an AI-agent-powered trading control backend with:

- **Modular API architecture** (routers, services, core models, startup wiring).
- **Planner → Executor → Evaluator** multi-agent orchestration flow for stocks.
- **Dedicated options intelligence subsystem** with multi-agent OODA pipeline.
- **Grounding/RAG-lite** using local strategy/reference documents.
- **Typed + guardrailed tools** with retry and circuit-breaker behavior.
- **Memory layers** (conversation, task-state, and DB-backed persistent run memory).

- Persistent execution traces are stored in the `agent_runs` table for replay and auditability.
- **Shadow mode** for virtual-trade analysis before live promotion.
- **Async DB integration** via SQLAlchemy async engine/session.

---

## Current Architecture

### High-level components

1. **API Layer (`api/routes`)**
   - Exposes endpoints for health, analysis, shadow mode, trades, performance, and options intelligence.
2. **Service Layer (`api/services`)**
   - `TradingService`: orchestration invocation + shadow-trade evaluation.
   - `AgentLearningService`: per-agent performance tracking and persistence.
   - `AgentMemoryService`: persistent run storage in DB.
   - `OptionsService`: options flow/screener intelligence with guardrailed multi-agent generation.
3. **Core Models (`api/core/models.py`)**
   - Pydantic request/response models.
   - SQLAlchemy ORM models (`Trade`, `AgentPerformance`, `AgentRun`).
4. **Agent Runtime (`multi_agent_orchestrator.py`)**
   - Planner, execution engine, reasoning model(s), tool layer, memory, evaluator.
5. **Infrastructure Runtime (`api/main.py`, `api/database.py`, `api/config.py`)**
   - App startup, DB connectivity checks, service registry wiring.

### Repository structure

```text
.
├── api/
│   ├── core/
│   │   └── models.py
│   ├── routes/
│   │   ├── analyze.py
│   │   ├── health.py
│   │   ├── options.py
│   │   ├── performance.py
│   │   └── trades.py
│   ├── services/
│   │   ├── learning.py
│   │   ├── memory.py
│   │   ├── options.py
│   │   ├── options_agents.py
│   │   └── trading.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── main_state.py
│   └── index.py
├── frontend/
│   └── src/
│       ├── components/options/
│       ├── lib/
│       └── pages/options.tsx
├── multi_agent_orchestrator.py
├── docs/
├── tests/
└── requirements.txt
```

---

## Infrastructure & Runtime

### Application stack

- **Python** 3.10+
- **FastAPI** for HTTP API
- **SQLAlchemy (async)** for data access
- **PostgreSQL** (expected via `DATABASE_URL`)
- **Anthropic (optional)** for live reasoning model calls
- **Next.js/React** for operator UI

### Config

Primary runtime config is in `api/config.py` via `pydantic-settings`.

Key env vars:

- `DATABASE_URL` (required for DB-backed runtime)
- `ANTHROPIC_API_KEY` (optional; if absent, deterministic local model is used)
- `ANTHROPIC_MODEL` (optional; defaults to `claude-sonnet-4-20250514`)
- `UW_API_KEY` (optional for live Unusual Whales MCP tool calls)
- `UNUSUAL_WHALES_MCP_URL` (optional; defaults to UW MCP endpoint)
- `FRONTEND_URL` (CORS origin)
- `NODE_ENV` (`development` | `staging` | `production`)

---

## Agent System Design

### Stocks orchestration

The stock pipeline is separated into layered concerns:

- Reasoning model layer
- Planner layer
- Execution layer
- Tool layer with guardrails
- Grounding layer
- Memory layer
- Evaluation layer

### Options orchestration (uniform multi-agent design)

The options pipeline is implemented as a dedicated agent chain:

1. `OPTIONS_ANALYST` (observe/orient market + flow context)
2. `OPTIONS_STRATEGIST` (regime + strategy candidate planning)
3. `OPTIONS_EXECUTOR` (build executable play templates)
4. `OPTIONS_GUARDRAIL` (risk thresholds + kill switch)
5. `OPTIONS_VALIDATOR` (quality/schema gate)

Each generation call returns:

- `items` (validated plays)
- `agent_trace` (agent-by-agent summaries)
- `guardrail` (kill-switch/rejection metadata)
- `task_plan` (decomposed OODA tasks)

---

## API Endpoints

### Health

- `GET /`
- `GET /api/health`
- `GET /api/options/health`

### Analysis

- `POST /api/analyze`
- `POST /api/shadow/analyze`
- `GET /api/shadow/evaluate/{symbol}?observed_price=...`

### Trades

- `GET /api/trades`
- `POST /api/trades`

### Performance

- `GET /api/performance/{agent_name}`
- `GET /api/performance`
- `GET /api/statistics`
- `GET /api/runs`

### Options (uniform route family)

- `GET /api/options/flow`
- `GET /api/options/screener`
- `GET /api/options/ticker/{symbol}`
- `POST /api/options/plays/generate`
- `POST /api/options/plays/close`
- `POST /api/options/learning/summary`
- `GET /api/options/performance`
- `GET /api/options/performance/{agent_name}`
- `GET /api/options/statistics`
- `GET /api/options/runs`

---

## Local Development

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Set environment variables

Example:

```bash
export DATABASE_URL='postgresql://user:pass@localhost:5432/trading_control'
export ANTHROPIC_API_KEY='your_key_optional'
export ANTHROPIC_MODEL='claude-sonnet-4-20250514'
export UW_API_KEY='your_uw_key_optional'
export UNUSUAL_WHALES_MCP_URL='https://api.unusualwhales.com/api/mcp'
export FRONTEND_URL='http://localhost:3000'
export NODE_ENV='development'
```

### 3) Run API

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4) Run tests

```bash
pytest -q
```

---

## Deployment

### Recommended deployment flow

1. Provision PostgreSQL.
2. Set runtime env vars (`DATABASE_URL`, optional model/API keys, `FRONTEND_URL`).
3. Deploy API service using ASGI entrypoint:
   - `api.main:app` (or compatibility entrypoint `api.index:app`)
4. Ensure startup health:
   - DB connectivity passes (`/api/health`)
5. Run smoke tests after deployment.

### Serverless compatibility

- `api/index.py` remains as a thin compatibility entrypoint.
- Main application wiring is centralized in `api/main.py`.

---

## Testing Strategy (Current)

The repository includes tests for:

- basic runtime sanity checks
- planner determinism and orchestrator behavior
- tool guardrail failures + circuit breaker
- contradictory data / low-consensus handling
- shadow-mode evaluation
- modular API structure checks
- options multi-agent output structure + telemetry contract checks

Run all tests:

```bash
pytest -q
```
