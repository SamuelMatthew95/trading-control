# Trading Control

A production-grade platform for orchestrating autonomous AI agents in real-time trading systems.

---

## Badges

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Framework](https://img.shields.io/badge/FastAPI-Async-green)
![Database](https://img.shields.io/badge/PostgreSQL-Async-blue)
![Architecture](https://img.shields.io/badge/Architecture-Multi--Agent-black)
![Status](https://img.shields.io/badge/Status-Active-success)

---

## Overview

Trading Control is a modular system for managing multi-agent AI workflows applied to financial trading.

It provides:

- Deterministic agent orchestration
- Safety-guarded execution
- Persistent memory and learning loops
- Real-time monitoring and performance tracking

---

## Documentation

| Resource        | Link |
|----------------|------|
| Documentation  | https://matthew.docs.buildwithfern.com/ |
| API Reference  | https://matthew.docs.buildwithfern.com/api-reference |
| Architecture   | https://matthew.docs.buildwithfern.com/architecture |

---

## Core Features

### Multi-Agent Orchestration
Planner → Executor → Evaluator pipeline with structured tool usage and validation.

### Shadow Mode
Run strategies in a simulated environment before enabling live execution.

### Persistent Memory
- Task-level memory
- Agent-level performance tracking via `agent_runs` table
- Long-term learning signals
- Database-backed persistent storage

### Safety Guardrails
- Typed tool interfaces
- Retry + fallback logic
- Circuit breaker protection

### Observability
- Agent-level metrics
- Execution tracing
- System-wide monitoring endpoints

---

## Architecture

![Architecture](./docs/architecture.png)

This system is a multi-agent, event-driven trading platform that integrates real-time market data, sentiment analysis, and machine learning for alpha generation and automated execution.

### System Components

| Layer | Components | Key Functions |
| :--- | :--- | :--- |
| **Data Sources** | Alpaca, Polygon, Binance | Ingests equity ticks, crypto, and news/options data. |
| **Ingestors** | Market & News (FinBERT) | Normalizes streams and performs NLP sentiment extraction. |
| **Event Bus** | Redis Streams | Handles market ticks, signals, orders, and risk alerts. |
| **Alpha Engine** | Microstructure, Sentiment, Macro | Multi-factor models (OFI, VWAP, FOMC, CPI) for signal generation. |
| **Reasoning** | IC-Weighted Combiner | LLM-powered agent with vector memory for signal synthesis. |
| **Risk & Execution** | Kelly Criterion, VWAP Engine | Manages drawdown, correlation, and smart order routing. |
| **Learning** | Vector Memory (pgvector) | Trade evaluation and PnL factor analysis for system feedback. |

### Key Features

- **Intelligence:** Uses **FinBERT** for financial sentiment and an **LLM-based Reasoning Agent** to weigh alpha factors
- **Performance:** Built on an **Asynchronous PostgreSQL** data layer and **Redis Streams** for sub-millisecond event handling
- **Risk Management:** Integrated **Kill Switch**, Drawdown Manager, and Kelly Criterion sizing
- **Observability:** Real-time **Next.js Dashboard** using WebSockets for live monitoring

### Tech Stack

- **Language:** Python (Async), TypeScript (Frontend)
- **Database:** PostgreSQL + `pgvector` (1536-dim embeddings)
- **Messaging:** Redis Streams
- **Frontend:** Next.js, Tailwind CSS, Shadcn/UI

---

## Quick Start

### Requirements

- Python 3.10+
- PostgreSQL

### Installation

```bash
git clone https://github.com/SamuelMatthew95/trading-control
cd trading-control
pip install -r requirements.txt
cp .env.example .env
```

### Run

```bash
uvicorn api.main:app --reload
```

### Test

```bash
pytest -q
```

---

## Configuration

```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/trading_control
ANTHROPIC_API_KEY=
FRONTEND_URL=http://localhost:3000
NODE_ENV=development
```

---

## API Surface

### Core

- `GET /health` 
- `POST /analyze` 
- `POST /shadow/analyze` 
- `GET /trades` 
- `POST /trading/start` 

### Monitoring

- `GET /performance/{agent}` 
- `GET /monitoring/overview` 
- `GET /dashboard` 

### Learning

- `POST /feedback/reinforce` 
- `POST /memory/annotations` 
- `GET /insights` 

Full docs: [https://matthew.docs.buildwithfern.com/api-reference](https://matthew.docs.buildwithfern.com/api-reference)

---

## Deployment

```bash
export DATABASE_URL=
export ANTHROPIC_API_KEY=
export FRONTEND_URL=
export NODE_ENV=production

uvicorn api.main:app
```

---

## Safety Model

- Guarded execution layer
- Trade risk constraints
- Circuit breaker system
- Shadow-mode validation before live promotion
- Full audit logging

---

## Observability

- Structured logs
- Per-agent performance tracking
- Execution tracing via run_id
- Learning feedback metrics

---

## Project Structure

```text
api/
  core/         # domain models, stream logic, DB readiness checks
  events/       # event bus + DLQ handling
  routes/       # FastAPI route modules
  services/     # orchestration, execution, ingestion services
  alembic/      # schema migration history
  database.py   # canonical async DB engine + session management
  db.py         # compatibility facade for legacy imports
frontend/       # Next.js dashboard
scripts/        # operational and validation scripts
tests/
  core/
  api/
  integration/
docs/
```

---

## Philosophy

This system is designed to behave less like a script and more like an operating system for trading intelligence.

---

## License

Internal use only.
