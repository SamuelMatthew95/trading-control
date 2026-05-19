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
  Event-driven trading orchestration with a multi-agent AI pipeline, realtime stream processing,<br/>
  and an operator-first dashboard built for safe, observable automation.
</p>

<p align="center">
  <a href="https://trading-control-khaki.vercel.app/dashboard">🚀 Live Dashboard</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/">📚 Fern Docs</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/docs/system-design/architecture">🏗️ Architecture</a>
  &nbsp;·&nbsp;
  <a href="https://matthew.docs.buildwithfern.com/api-reference/api-reference/">🧩 API Reference</a>
</p>

---

## Why this project exists

Trading Control is designed to keep algorithmic execution **adaptive** without sacrificing **determinism**:

- AI agents can reason, reflect, and propose improvements.
- Infrastructure enforces idempotency, traceability, and safe persistence routes.
- Operators retain realtime observability and manual override capability.

## Platform snapshot

| Layer | Technology | Purpose |
|---|---|---|
| Backend | FastAPI (Python 3.10+) | APIs, orchestration, event ingestion |
| Frontend | Next.js 14 (TypeScript) | Operator dashboard and control plane |
| Database | PostgreSQL 15+ + pgvector | Durable state, audit history, vector memory |
| Event Bus | Redis Streams | Agent-to-agent communication and fanout |
| Broker | Alpaca (paper trading) | Market data and execution simulation |

---

## Agent pipeline

<p align="center">
  <img src="docs/img/agent-pipeline.svg" alt="Agent Pipeline" width="860"/>
</p>

| Agent | Input Stream(s) | Output Stream | Responsibility |
|---|---|---|---|
| SignalGenerator | `market_ticks` | `signals` | Normalize ticks into typed market signals |
| ReasoningAgent | `signals` | `decisions` | Produce candidate actions with LLM reasoning |
| GradeAgent | `executions`, `trade_performance` | `agent_grades` | Score quality and execution outcomes |
| ICUpdater | `trade_performance` | `ic_weights` | Reweight alpha factors from realized performance |
| ReflectionAgent | `trade_performance`, `agent_grades` | `reflection_outputs` | Extract patterns and failure modes |
| StrategyProposer | `reflection_outputs` | `proposals` | Convert insights into operator-ready proposals |
| NotificationAgent | all key streams | `notifications` | Route alerts by severity and audience |

---

## Core guarantees

<p align="center">
  <img src="docs/img/architecture.svg" alt="System Architecture" width="860"/>
</p>

| Guarantee | How it is enforced |
|---|---|
| Deterministic writes | `SafeWriter` is the canonical write path |
| Idempotent behavior | Keys prevent duplicate event/order side effects |
| End-to-end traceability | `trace_id` propagates across events, runs, logs, and memory |
| Memory-first resilience | Runtime fallback serves in-memory state when DB is unavailable |
| Replayability | Event history can rebuild operational state |

---

## Quick start

### 1) Prerequisites

- Python 3.10+
- PostgreSQL 15+ with `pgvector`
- Redis 5.0+

### 2) Install

```bash
git clone https://github.com/SamuelMatthew95/trading-control.git
cd trading-control
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3) Configure

```bash
cp .env.example .env
```

Minimum required settings:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trading_control
REDIS_URL=redis://localhost:6379/0
GROQ_API_KEY=your_groq_key
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
```

### 4) Run services

```bash
# Backend API
uvicorn api.main:app --reload

# Frontend dashboard (separate terminal)
cd frontend && npm install && npm run dev
```

---

## Validation commands (must pass before commit)

```bash
ruff check . --fix
ruff format .
ruff format --check .
pytest tests/core tests/api -v --tb=short
pytest tests/integration -v --tb=short
```

---

## Docs map

For comprehensive usage and operational detail, prefer the hosted Fern documentation first, then deep-dive files in `/docs`.

| Resource | Link |
|---|---|
| 🌐 Fern docs home | https://matthew.docs.buildwithfern.com/ |
| 🧩 API reference | https://matthew.docs.buildwithfern.com/api-reference/api-reference/ |
| 🏗️ Architecture deep dive | [docs/architecture.md](docs/architecture.md) |
| 🧪 Testing standards | [docs/testing.md](docs/testing.md) |
| 🛠️ Development workflow | [docs/development-guide.md](docs/development-guide.md) |
| 🚢 Deployment checklist | [docs/deployment-guide.md](docs/deployment-guide.md) |
| 🧯 Troubleshooting playbook | [docs/troubleshooting/README.md](docs/troubleshooting/README.md) |
| 🤖 Agent implementation guide | [docs/AGENTS.md](docs/AGENTS.md) |
| 🔌 MCP integration notes | [docs/mcp.md](docs/mcp.md) |

---

## Repository layout

```text
trading-control/
├── api/                        # FastAPI app and backend services
├── frontend/                   # Next.js operator dashboard
├── docs/                       # Architecture, guides, and troubleshooting
├── tests/                      # Unit, API, and integration suites
├── requirements.txt            # Runtime + test dependencies
├── ruff.toml                   # Lint and formatting config
├── pytest.ini                  # Pytest defaults
└── render.yaml                 # Render deployment config
```

## License

Internal use only.
