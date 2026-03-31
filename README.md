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

The platform runs 7 specialized agents connected via Redis Streams:

```mermaid
flowchart TD
    MT([market_ticks]) --> SG

    SG["<b>SignalGenerator</b><br/>Converts ticks to typed signals"]
    SG -->|signals| RA

    RA["<b>ReasoningAgent</b><br/>LLM-powered trade decisions<br/><i>Groq / Anthropic</i>"]
    RA -->|decisions| GA

    GA["<b>GradeAgent</b><br/>Scores performance<br/><i>accuracy · IC · cost · latency</i>"]

    GA --> IC
    GA --> RF
    GA --> SP
    GA --> NA

    IC["<b>ICUpdater</b><br/>Reweights alpha factors"]
    RF["<b>ReflectionAgent</b><br/>Finds trade patterns"]
    SP["<b>StrategyProposer</b><br/>Creates proposals"]
    NA["<b>NotificationAgent</b><br/>Routes alerts"]

    style MT fill:#1e293b,color:#94a3b8,stroke:#334155
    style SG fill:#0f172a,color:#38bdf8,stroke:#0ea5e9
    style RA fill:#0f172a,color:#a78bfa,stroke:#7c3aed
    style GA fill:#0f172a,color:#34d399,stroke:#059669
    style IC fill:#1e293b,color:#cbd5e1,stroke:#475569
    style RF fill:#1e293b,color:#cbd5e1,stroke:#475569
    style SP fill:#1e293b,color:#cbd5e1,stroke:#475569
    style NA fill:#1e293b,color:#cbd5e1,stroke:#475569
```

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

## Architecture

```mermaid
flowchart LR
    PG[("PostgreSQL\nSource of Truth")]
    RS["Redis Streams\nDelivery · Fan-out"]
    AG["AI Agents\nStream consumers"]
    DB["Next.js Dashboard\nSSE · WebSocket"]

    PG --> RS --> AG --> DB

    style PG fill:#1e3a5f,color:#93c5fd,stroke:#3b82f6
    style RS fill:#3b1f1f,color:#fca5a5,stroke:#ef4444
    style AG fill:#1a2e1a,color:#86efac,stroke:#22c55e
    style DB fill:#1e1e3b,color:#c4b5fd,stroke:#8b5cf6
```

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
│   ├── core/                   # Core unit tests + FakeSession/FakeRedis
│   └── api/                    # Per-router endpoint tests
├── fakeredis/                  # In-repo async FakeRedis shim for tests
├── requirements.txt            # All runtime + dev/test dependencies
├── ruff.toml                   # Linting config (line-length 100, py310)
├── pytest.ini                  # Pytest configuration
├── render.yaml                 # Render deployment config
└── CHANGELOG.md                # Full change history
```

> **Note on `fakeredis/`:** Kept in-repo intentionally. Provides the async `FakeAsyncRedis` used by all tests. Removing it breaks test fixtures.

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

## License

Internal use only.
