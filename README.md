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
- Agent-level performance tracking
- Long-term learning signals

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

### System Overview

```text
                ┌──────────────────────┐
                │        Client        │
                └─────────┬────────────┘
                          │
                ┌─────────▼────────────┐
                │      API Layer       │  (FastAPI)
                └─────────┬────────────┘
                          │
        ┌─────────────────▼─────────────────┐
        │        Agent Orchestrator         │
        │                                  │
        │  Planner → Executor → Evaluator  │
        └─────────┬────────────┬───────────┘
                  │            │
        ┌─────────▼───┐  ┌─────▼─────────┐
        │ Tool Layer  │  │ Memory Layer  │
        │ (Guarded)   │  │ (State + RL)  │
        └─────────────┘  └─────┬─────────┘
                               │
                    ┌──────────▼──────────┐
                    │     Data Layer      │
                    │   PostgreSQL Async  │
                    └─────────────────────┘
```

### Detailed Architecture

```
DATA SOURCES                    INGESTORS                     EVENT BUS
┌─────────┬─────────┬─────────┐  ┌─────────┬─────────┐  ┌─────────────────────────┐
│ Alpaca  │ Polygon │ Binance │  │ Market  │  News   │  │   Redis Streams          │
│equity   │news +   │crypto   │  │Ingestor │Ingestor │  │   Event Bus             │
│ticks    │options  │ticks    │  │stream   │FinBERT  │  │   market_ticks · signals │
└─────────┴─────────┴─────────┘  └─────────┴─────────┘  │   orders · executions   │
                                                    │   risk_alerts · learning │
                                                    └─────────────────────────┘
                                                                │
                    ALPHA ENGINE                                │
┌─────────┬─────────┬─────────┬─────────┬─────────┐              │
│Micro-   │Sentiment│Momentum │Regime   │Macro    │              │
│structure│ Factors │ Factors │ Router  │ Agent   │              │
│OFI · VWAP│news ·   │cross-   │RISK_ON/ │FOMC ·   │              │
│spread   │options  │sect     │OFF      │CPI      │              │
└─────────┴─────────┴─────────┴─────────┴─────────┘              │
           │                    │                              │
           └─────────┬──────────┘                              │
                     │                                       │
        ┌─────────────▼─────────────┐                         │
        │   IC-Weighted Combiner    │                         │
        │   Reasoning Agent         │                         │
        │   LLM + vector memory     │                         │
        └─────────────┬─────────────┘                         │
                      │                                       │
                      ▼                                       ▼
        RISK & SIZING           EXECUTION                LEARNING & FEEDBACK
┌─────────┬─────────┬─────────┐  ┌─────────┬─────────┐  ┌─────────┬─────────┐
│ Risk    │Drawdown │Correla- │  │Execu-   │Paper    │  │Trade    │Vector   │
│ Engine  │ Manager │tion     │  │tion     │Broker   │  │Evaluator│Memory   │
│kill     │Kelly    │Manager  │  │Engine   │simulated│  │PnL ·    │pgvector │
│switch   │tier     │covariance│  │VWAP     │fills    │  │factor   │1536-dim │
└─────────┴─────────┴─────────┘  └─────────┴─────────┘  └─────────┴─────────┘
                      │                                       │
                      ▼                                       ▼
                DASHBOARD
┌─────────────────────────────────┐
│ Next.js Dashboard                │
│ WebSocket + REST                 │
│ Overview · Trading · Agents     │
│ Learning · Alpha Research       │
└─────────────────────────────────┘
```

### System Layers

- **Data Sources** - Market data providers (Alpaca, Polygon, Binance, FRED, CryptoQuant)
- **Ingestors** - Data normalization and processing (Market, News, Options, On-chain)
- **Event Bus** - Redis Streams for decoupled messaging
- **Alpha Engine** - Signal generation and reasoning (Factors, Combiner, LLM Agent)
- **Risk & Sizing** - Safety guardrails and position management
- **Execution** - Order execution with paper and live brokers
- **Learning** - Performance tracking and memory systems
- **Dashboard** - Unified control plane

### Execution Flow

```text
Planner
  ↓
Executor
  ↓
Evaluator
  ↓
Memory
  ↓
Learning Loop
```

Each stage is isolated, observable, and testable.

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
agents/
tools/
memory/
models/
services/
tests/
```

---

## Philosophy

This system is designed to behave less like a script and more like an operating system for trading intelligence.

---

## License

Internal use only.
