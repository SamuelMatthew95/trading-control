# Trading Control

Production-oriented multi-agent trading control system with a modular FastAPI backend, planner/executor agent orchestration, guardrailed tools, and evaluation-focused workflows.

## Overview

This repository provides an AI-agent-powered trading control backend with:

- **Modular API architecture** (routers, services, core models, startup wiring).
- **Planner → Executor → Evaluator** multi-agent orchestration flow.
- **Grounding/RAG-lite** using local strategy/reference documents.
- **Typed + guardrailed tools** with retry and circuit-breaker behavior.
- **Memory layers** (conversation, task-state, and DB-backed persistent run memory).
- **Shadow mode** for virtual-trade analysis before live promotion.
- **Async DB integration** via SQLAlchemy async engine/session.

---

## Current Architecture

### High-level components

1. **API Layer (`api/routes`)**
   - Exposes endpoints for health, analysis, shadow mode, trades, and performance.
2. **Service Layer (`api/services`)**
   - `TradingService`: orchestration invocation + shadow-trade evaluation.
   - `AgentLearningService`: per-agent performance tracking and persistence.
3. **Core Models (`api/core/models.py`)**
   - Pydantic request/response models.
   - SQLAlchemy ORM models (`Trade`, `AgentPerformance`).
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
│   │   ├── performance.py
│   │   └── trades.py
│   ├── services/
│   │   ├── learning.py
│   │   └── trading.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── main_state.py
│   └── index.py
├── multi_agent_orchestrator.py
├── skills/trade-bot/references/
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

### Config

Primary runtime config is in `api/config.py` via `pydantic-settings`.

Key env vars:

- `DATABASE_URL` (required for DB-backed runtime)
- `ANTHROPIC_API_KEY` (optional; if absent, deterministic local model is used)
- `FRONTEND_URL` (CORS origin)
- `NODE_ENV` (`development` | `staging` | `production`)

---

## Agent System Design

The orchestrator is intentionally separated into layered concerns:

- **Reasoning model layer**
  - `AnthropicReasoningModel` (live API calls + retry)
  - `DeterministicReasoningModel` (fallback deterministic behavior)
- **Planner layer**
  - deterministic step plan (`signal`, `consensus`, `risk`, `sizing`, `decision`)
- **Execution layer**
  - step-specific execution and data flow
- **Tool layer**
  - `TradeTools` with asset/timeframe guardrails + retry/circuit breaker
- **Grounding layer**
  - `DocumentRetriever` reading local markdown references
- **Memory layer**
  - conversation memory
  - task state memory
  - persistent memory (`agent_runs` database table)
- **Evaluation layer**
  - trajectory and output-shape checks

This keeps planning, execution, and evaluation distinct and testable.

---

## API Endpoints

### Health

- `GET /`
- `GET /api/health`

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
2. Set runtime env vars (`DATABASE_URL`, optional `ANTHROPIC_API_KEY`, `FRONTEND_URL`).
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

Run all tests:

```bash
pytest -q
```

---

## Operational Notes

- Persistent execution memory is stored in PostgreSQL (`agent_runs`) through the API memory service.
- Local file artifacts may still appear for standalone orchestrator runs, but production API mode persists traces in the database.
- For better traceability, integrate structured telemetry (e.g., OpenTelemetry/Langfuse) on top of current call traces.

---

## Roadmap Suggestions

- Add route-level integration tests with mocked DB sessions.
- Add richer trajectory replay/regression datasets.
- Add strict schema validation for agent step outputs before state transitions.
- Add automated promotion logic for shadow-mode → live based on KPI thresholds.

---

## License

Internal project / no explicit OSS license declared.
