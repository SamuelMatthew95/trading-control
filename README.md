<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Next.js-14-000000?style=for-the-badge&logo=next.js&logoColor=white" alt="Next.js 14"/>
  <img src="https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL 15+"/>
  <img src="https://img.shields.io/badge/Redis-5.0%2B-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis 5.0+"/>
  <img src="https://img.shields.io/badge/Render-Backend-46E3B7?style=for-the-badge&logo=render&logoColor=white" alt="Render"/>
  <img src="https://img.shields.io/badge/Vercel-Frontend-000000?style=for-the-badge&logo=vercel&logoColor=white" alt="Vercel"/>
</p>

<h1 align="center">Trading Control</h1>

<p align="center">
  An event-driven algorithmic trading platform with a multi-agent AI pipeline,<br/>
  real-time Redis Streams, and a live operator dashboard.
</p>

<p align="center">
  <a href="https://trading-control-khaki.vercel.app/dashboard">Live Dashboard</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/">API Docs</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/docs/system-design/architecture">Architecture</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/api-reference/api-reference/">API Reference</a>
</p>

---

## Overview

**Trading Control** is a production-grade, event-driven trading orchestration platform built on a pipeline of specialized AI agents communicating exclusively through Redis Streams.

| Layer | Technology | Purpose |
|---|---|---|
| Backend | FastAPI (Python 3.10+) | Control APIs, telemetry, agent orchestration |
| Frontend | Next.js 14 (TypeScript) | Live operator dashboard |
| Database | PostgreSQL 15+ with pgvector | Persistent state, vector memory, audit trail |
| Streams | Redis 5.0+ | Event bus, agent communication, pub/sub |
| Market Data | Alpaca API (paper mode) | Live price ticks and order execution |

---

## Agent Pipeline

<p align="center">
  <img src="docs/img/agent-pipeline.svg" alt="Agent Pipeline" width="860"/>
</p>

| Agent | Listens To | Publishes To | Purpose |
|---|---|---|---|
| SignalGenerator | `market_ticks` | `signals` | Converts ticks to typed signals |
| ReasoningAgent | `signals` | `decisions` | LLM-based trade decisions |
| GradeAgent | `executions`, `trade_performance` | `agent_grades` | Scores performance |
| ICUpdater | `trade_performance` | `ic_weights` | Reweights alpha factors |
| ReflectionAgent | `trade_performance`, `agent_grades` | `reflection_outputs` | Finds patterns |
| StrategyProposer | `reflection_outputs` | `proposals` | Creates concrete proposals |
| NotificationAgent | All streams | `notifications` | Routes alerts by severity |

---

## Agentic AI learnings applied

Inspired by common agentic design patterns (reflection, planning, tool use, and multi-agent coordination), this codebase applies the following in production:

- **Reflection loop**: `ReflectionAgent` runs evaluator/optimizer-style refinement when first-pass hypotheses are too weak.
- **Planning before action**: `StrategyProposer` ranks high-confidence hypotheses by expected impact before proposal generation.
- **Tool use with safe fallbacks**: agents rely on typed services (DB, Redis streams, LLM client) and degrade safely when external calls fail.
- **Supervised autonomy**: `AgentSupervisor` provides self-healing restarts with rate-limits to prevent crash/restart thrashing.

This keeps autonomy high while retaining operational guardrails for a trading environment.

---

## Architecture

<p align="center">
  <img src="docs/img/architecture.svg" alt="System Architecture" width="860"/>
</p>

Core guarantees:

| Guarantee | Mechanism |
|---|---|
| **Determinism** | All writes go through `SafeWriter` — same input, same output |
| **Idempotency** | `idempotency_key` prevents duplicate orders and events |
| **Traceability** | `trace_id` spans every event → agent run → log → vector memory |
| **Replayability** | Full system state rebuildable from the `events` table |

---

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 15+ with the pgvector extension
- Redis 5.0+

### Installation

```bash
git clone https://github.com/SamuelMatthew95/trading-control.git
cd trading-control
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Minimum required variables:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trading_control
REDIS_URL=redis://localhost:6379/0
GROQ_API_KEY=your_groq_key
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
```

### Run

```bash
# Backend API
uvicorn api.main:app --reload

# Frontend dashboard (separate terminal)
cd frontend && npm install && npm run dev
```

---

## Testing

```bash
# Full test suite
pytest tests/ -v --tb=short

# With coverage
pytest tests/ -v --tb=short --cov=api

# Specific categories
pytest tests/core/ -v    # Core unit tests
pytest tests/api/ -v     # API endpoint tests
```

All 117 tests pass. Zero failures required before any merge.

---

## CI/CD

Every push runs:

```bash
ruff check . --fix                        # Lint
ruff format --check .                     # Format
ruff check . --select=E9,F63,F7,F82      # Critical errors
pytest tests/ -v --tb=short              # Full test suite
```

Frontend: ESLint + TypeScript check + production build.

---

## Repository Layout

```
trading-control/
├── api/                        # FastAPI app and all backend logic
│   ├── main.py                 # App wiring, middleware, router registration
│   ├── config.py               # Pydantic settings — all env vars live here
│   ├── database.py             # Async engine, session, health checks
│   ├── observability.py        # log_structured() — the only logging function
│   ├── events/
│   │   └── bus.py              # Redis Streams EventBus
│   ├── routes/                 # 13 HTTP route modules
│   ├── services/
│   │   └── agents/
│   │       ├── pipeline_agents.py   # GradeAgent, ICUpdater, Reflection, etc.
│   │       └── reasoning_agent.py   # LLM-powered ReasoningAgent
│   └── core/
│       └── writer/
│           └── safe_writer.py  # The only authorized write path
├── frontend/                   # Next.js 14 operator dashboard
├── docs/                       # Architecture, deployment, contributing
├── tests/                      # Unit, API, agent, and integration tests
│   ├── core/                   # Core unit tests + FakeAsyncSession
│   └── api/                    # Per-router endpoint tests
├── requirements.txt            # All runtime + dev/test dependencies
├── ruff.toml                   # Linting config (line-length 100, py310)
├── pytest.ini                  # Pytest configuration
├── render.yaml                 # Render deployment config
└── CHANGELOG.md                # Full change history
```

---

## Deployment

| Service | Platform | URL |
|---|---|---|
| Backend API | Render | Auto-deploys on push to `main` |
| Frontend | Vercel | https://trading-control-khaki.vercel.app/dashboard |
| Database | Render PostgreSQL | Managed, pgvector enabled |
| Redis | Render Redis | Managed |

See [docs/deployment-guide.md](docs/deployment-guide.md) for the full checklist and all required environment variables.

---

## Documentation

| Resource | Link |
|---|---|
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Development Guide | [docs/development-guide.md](docs/development-guide.md) |
| Deployment Guide | [docs/deployment-guide.md](docs/deployment-guide.md) |
| Agent Guide | [docs/AGENTS.md](docs/AGENTS.md) |
| Testing Guide | [docs/testing.md](docs/testing.md) |
| Contributing | [docs/contributing.md](docs/contributing.md) |
| API Reference | [matthew.docs.buildwithfern.com](https://matthew.docs.buildwithfern.com/api-reference/api-reference/) |

---

## Operator UI Design System

### Density system
- Button height: **28px**
- Button radius: **4px**
- Status chip radius: **6px**
- Header height: **48px**
- Level column width in terminal tables: **44px**

### Typography system
- Controls: **JetBrains Mono**, uppercase, 11px, `letter-spacing: 0.04em`
- Metric columns: `font-variant-numeric: tabular-nums`
- Status chips: sentence case labels only

### Color + state mapping
- Buttons:
  - Primary: slate-100 background + slate-950 text
  - Secondary: transparent + slate border
  - Ghost: borderless + muted slate text
  - Destructive: transparent + rose-400 border/text
  - Disabled: slate-700 border + slate-600 text
- Status chips (strict enum): **Live / Stale / Error / Idle**
  - Live: emerald-300 tint + dot
  - Stale: amber-300 tint + dot
  - Error: rose-300 tint + dot
  - Idle: neutral slate border/text, no colored dot

### Animation spec
- Use subtle color transitions only.
- Skeleton loaders are the default loading pattern.
- Spinners are allowed only for blocking operations.
- No glow/gradient decoration in operator surfaces.

### Empty/loading state rules
- Required empty states:
  - `No active agents`
  - `No orders today`
  - `Stream disconnected`
- Empty-state containers use dashed borders and low-contrast slate text.
- Loading states use skeletons in non-blocking views.

### Table system rules
- Sticky headers for scrollable tables.
- Hover highlight for rows (no density expansion on hover).
- Sort indicators: `▴` and `▾`.
- Numeric columns are fixed-aligned and tabular.

### Form component rules
- Inline keyboard hints (`<kbd>`) for primary actions (`⏎`) and escape/cancel (`ESC`).
- Vertical divider between primary and secondary action groups.
- No pill shapes (`rounded-full`) for control surfaces.

---

## License

Internal use only.
