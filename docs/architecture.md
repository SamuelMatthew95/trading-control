# 🏗️ Trading Control Architecture

## System Overview

Trading Control is a modular, production-oriented multi-agent trading platform composed of:

- **FastAPI backend** with clear route/service/model boundaries.
- **Stock intelligence pipeline** backed by `MultiAgentOrchestrator`.
- **Options intelligence pipeline** with dedicated multi-agent OODA chain.
- **Async PostgreSQL persistence** for trades, performance metrics, and run traces.
- **Next.js frontend** for operator workflows and monitoring.

---

## Backend Architecture

### Layered structure

```text
api/
├── core/
│   └── models.py          # Pydantic + SQLAlchemy models
├── routes/
│   ├── health.py          # Root/system health
│   ├── analyze.py         # Stock analysis + shadow mode
│   ├── trades.py          # Trade history CRUD
│   ├── performance.py     # Global performance/statistics/runs
│   └── options.py         # Options flow/screener/plays/perf/stats/runs
├── services/
│   ├── trading.py         # Stock orchestration service
│   ├── learning.py        # Agent performance persistence
│   ├── memory.py          # Run trace persistence
│   ├── options.py         # Options orchestration service
│   └── options_agents.py  # Options specialist agents
├── main_state.py          # Dependency/service registry
└── main.py                # App bootstrap + router wiring
```

### Startup/service wiring

- `api/main.py` initializes DB and services.
- `api/main_state.py` provides dependency accessors (`get_*_service`).
- Routers consume services via FastAPI `Depends`.

---

## Stock Intelligence Flow

Stock analysis uses `MultiAgentOrchestrator` via `TradingService`:

1. Signal ingestion
2. Planner decomposition
3. Consensus/risk/sizing decisions
4. Structured trade decision output
5. Optional shadow evaluation and memory persistence

Routes:

- `POST /api/analyze`
- `POST /api/shadow/analyze`
- `GET /api/shadow/evaluate/{symbol}`

---

## Options Intelligence Flow (Uniform Multi-Agent Design)

Options uses a dedicated service (`OptionsService`) and specialist agents (`options_agents.py`):

1. **OPTIONS_ANALYST** → market/flow orientation.
2. **OPTIONS_STRATEGIST** → regime-aware candidate planning.
3. **OPTIONS_EXECUTOR** → executable play templates.
4. **OPTIONS_GUARDRAIL** → risk constraints + kill-switch.
5. **OPTIONS_VALIDATOR** → output quality/schema gate.

Each generation response returns:

- `items` (validated plays)
- `agent_trace` (human-readable chain-of-responsibility summaries)
- `guardrail` (rejections/kill-switch metadata)
- `task_plan` (decomposed orchestration tasks)
- `model` (configured LLM model identifier)

### Options route family

- `GET /api/options/health`
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

## Data & Persistence

### Core tables

- `trades`
- `agent_performance`
- `agent_runs`

### Run observability

- Global runs available via `GET /api/runs`.
- Options-specific runs are tagged (`task_id` prefix `options-`) and surfaced via `GET /api/options/runs`.

---

## Configuration

Key runtime variables:

- `DATABASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL` (default: `claude-sonnet-4-20250514`)
- `UW_API_KEY`
- `UNUSUAL_WHALES_MCP_URL`
- `FRONTEND_URL`

---

## Frontend Integration

Options UI lives in `frontend/src/pages/options.tsx` and consumes `/api/options/*` proxy routes.

Major UI sections:

- Flow feed (filters, refresh cadence)
- Screener (sorting/filtering + ticker details)
- Confirmed plays (generate/accept/monitor/close)
- Learning summary (history-driven feedback)
- Agent trace + task plan visibility for operator observability
