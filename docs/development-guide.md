# Development Guide

## Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL

## 1) Install dependencies

```bash
pip install -r requirements.txt
cd frontend && npm install
```

## 2) Configure environment

Create `.env` (or export env vars) with at least:

```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/trading_control
ANTHROPIC_API_KEY=optional
FRONTEND_URL=http://localhost:3000
NODE_ENV=development
```

## 3) Run backend

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## 4) Run frontend (optional for full-stack local dev)

```bash
cd frontend
npm run dev
```

## 5) Validate quickly

- API docs: `http://localhost:8000/docs`
- Health endpoint: `GET /api/health`

## Common issues

- `DATABASE_URL is required`: set a Postgres connection string in `.env`.
- DB connection fails on startup: verify Postgres is running and reachable.
- CORS issues in local dev: set `FRONTEND_URL` to your frontend origin.
