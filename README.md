<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Next.js-14-000000?style=for-the-badge&logo=next.js&logoColor=white" alt="Next.js 14"/>
  <img src="https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL 15+"/>
  <img src="https://img.shields.io/badge/Redis-5.0%2B-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis 5.0+"/>
  <img src="https://img.shields.io/badge/Render-Backend-46E3B7?style=for-the-badge&logo=render&logoColor=white" alt="Render"/>
  <img src="https://img.shields.io/badge/Vercel-Frontend-000000?style=for-the-badge&logo=vercel&logoColor=white" alt="Vercel"/>
</p>

<h1 align="center">⚡ Trading Control</h1>

<p align="center">
  An event-driven algorithmic trading platform with a multi-agent AI pipeline,<br/>
  real-time Redis Streams, and a live operator dashboard.
</p>

<p align="center">
  <a href="https://trading-control-khaki.vercel.app/dashboard">🖥️ Live Dashboard</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/">📖 API Docs</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/docs/system-design/architecture">🏗️ Architecture</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/api-reference/api-reference/">🔌 API Reference</a>
</p>

---

## 🗺️ Overview

**Trading Control** is a production-grade, event-driven trading orchestration platform built on a pipeline of specialized AI agents communicating exclusively through Redis Streams.

| Layer | Technology | Purpose |
|---|---|---|
| 🐍 Backend | FastAPI (Python 3.10+) | Control APIs, telemetry, agent orchestration |
| ⚛️ Frontend | Next.js 14 (TypeScript) | Live operator dashboard |
| 🐘 Database | PostgreSQL 15+ with pgvector | Persistent state, vector memory, audit trail |
| ⚡ Streams | Redis 5.0+ | Event bus, agent communication, pub/sub |
| 📈 Market Data | Alpaca API (paper mode) | Live price ticks and order execution |

---

## 🤖 Agent Pipeline

The platform runs 7 specialized agents connected via Redis Streams:

```
market_ticks
     │
     ▼
┌──────────────────┐
│  SignalGenerator  │  Converts raw price ticks → trading signals
└────────┬─────────┘
         │ signals
         ▼
┌──────────────────┐
│  ReasoningAgent   │  LLM-powered decision engine (Groq / Anthropic)
└────────┬─────────┘
         │ decisions
         ▼
┌──────────────────┐
│    GradeAgent    │  Scores agent performance (accuracy, IC, cost, latency)
└────────┬─────────┘
         │
   ┌─────┴──────┬──────────────┬──────────────┐
   ▼            ▼              ▼              ▼
ICUpdater  ReflectionAgent  StrategyProposer  NotificationAgent
(weights)    (patterns)       (proposals)      (alerts)
```

| Agent | Listens To | Publishes To | Purpose |
|---|---|---|---|
| 🎯 **SignalGenerator** | `market_ticks` | `signals` | Converts ticks to typed signals |
| 🧠 **ReasoningAgent** | `signals` | `decisions` | LLM-based trade decisions |
| 📊 **GradeAgent** | `executions`, `trade_performance` | `agent_grades` | Scores performance |
| 📐 **ICUpdater** | `trade_performance` | `ic_weights` | Reweights alpha factors |
| 🔍 **ReflectionAgent** | `trade_performance`, `agent_grades` | `reflection_outputs` | Finds patterns |
| 💡 **StrategyProposer** | `reflection_outputs` | `proposals` | Creates concrete proposals |
| 🔔 **NotificationAgent** | All streams | `notifications` | Routes alerts by severity |

---

## 🏗️ Architecture

```
PostgreSQL (Source of Truth)
        │
        ▼
  Redis Streams (Delivery / Fan-out)
        │
        ▼
  Agents (Consumers — never modify source truth)
        │
        ▼
  Next.js Dashboard (Real-time via SSE + WebSocket)
```

**Core guarantees:**

- **🔒 Determinism** — All writes go through `SafeWriter`; same input → same output
- **🔁 Idempotency** — `idempotency_key` prevents duplicate orders and events
- **🔎 Traceability** — `trace_id` spans every event → agent run → log → vector memory
- **📼 Replayability** — Full system state rebuildable from the `events` table

---

## 🚀 Quick Start

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
pip install -r requirements-dev.txt
```

### Configuration

```bash
cp .env.example .env
```

Minimum required variables:

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trading_control

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM (choose one)
GROQ_API_KEY=your_groq_key
ANTHROPIC_API_KEY=your_anthropic_key

# Alpaca (paper trading)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true

# App
LOG_LEVEL=INFO
ENABLE_SIGNAL_SCHEDULER=false
```

### Run

```bash
# Backend API
uvicorn api.main:app --reload

# Frontend dashboard (separate terminal)
cd frontend && npm install && npm run dev
```

---

## 🧪 Testing

```bash
# Full test suite
pytest tests/ -v --tb=short

# With coverage
pytest tests/ -v --tb=short --cov=api

# Specific categories
pytest tests/agents/ -v    # Agent tests
pytest tests/api/ -v       # API endpoint tests
```

All 117 tests pass. Zero failures are required before any merge.

---

## ✅ CI/CD

Every push to `main` runs:

```bash
ruff check . --fix                        # Lint
ruff format --check .                     # Format
ruff check . --select=E9,F63,F7,F82      # Critical errors
pytest tests/ -v --tb=short              # Full test suite
```

Frontend: ESLint + TypeScript check + production build.

---

## 📁 Repository Layout

```
trading-control/
├── api/                        # FastAPI app and all backend logic
│   ├── main.py                 # App wiring, middleware, router registration
│   ├── config.py               # Settings and env validation (Pydantic)
│   ├── database.py             # Async engine, session, health checks
│   ├── observability.py        # Structured logging (log_structured)
│   ├── events/
│   │   └── bus.py              # Redis Streams EventBus
│   ├── routes/                 # 13 HTTP route modules
│   ├── services/
│   │   └── agents/
│   │       ├── pipeline_agents.py   # GradeAgent, ICUpdater, Reflection, etc.
│   │       └── reasoning_agent.py   # LLM-powered reasoning
│   └── core/
│       ├── db/                 # Session management, migrations
│       └── writer/
│           └── safe_writer.py  # The only authorized write path
├── frontend/                   # Next.js 14 operator dashboard
│   └── src/
│       └── components/         # PipelineHealthBar, AgentsSection, SystemSection
├── docs/                       # Architecture, deployment, contributing
├── tests/                      # Unit, API, agent, and integration tests
│   ├── agents/                 # Per-agent test files
│   └── api/                    # Per-router test files
├── fakeredis/                  # In-repo async FakeRedis shim for tests
├── scripts/                    # Operational and validation helpers
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Dev/test dependencies
├── ruff.toml                   # Linting config (line-length 100, py310)
├── pytest.ini                  # Pytest configuration
└── CHANGELOG.md                # Full change history
```

> **Note on `fakeredis/`:** This folder is intentionally kept in-repo. It provides a minimal async `FakeAsyncRedis` implementation used by tests. Removing it will break all test fixtures that import `fakeredis` directly.

---

## 🌐 Deployment

| Service | Platform | Notes |
|---|---|---|
| 🐍 Backend API | Render | Auto-deployed on push to `main` |
| ⚛️ Frontend | Vercel | [trading-control-khaki.vercel.app](https://trading-control-khaki.vercel.app/dashboard) |
| 🐘 Database | Render PostgreSQL | Managed, pgvector enabled |
| ⚡ Redis | Render Redis | Managed |

Additional Render environment variables required:

```env
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
MARKET_DATA_PROVIDER=alpaca
DATABASE_URL=<render-postgres-url>
REDIS_URL=<render-redis-url>
```

---

## 📖 Documentation

| Resource | Link |
|---|---|
| 📐 Architecture Overview | [System Design Docs](https://matthew.docs.buildwithfern.com/docs/system-design/architecture) |
| 🔌 API Reference | [Fern API Reference](https://matthew.docs.buildwithfern.com/api-reference/api-reference/) |
| 🤖 Agent Guide | [docs/AGENTS.md](docs/AGENTS.md) |
| 🏗️ Development Guide | [docs/development-guide.md](docs/development-guide.md) |
| 🚢 Deployment Guide | [docs/deployment-guide.md](docs/deployment-guide.md) |
| 🤝 Contributing | [docs/contributing.md](docs/contributing.md) |
| 🧪 Testing Guide | [docs/testing.md](docs/testing.md) |

---

## 🛡️ License

Internal use only.
