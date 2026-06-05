# Development Guide

## Prerequisites

- Python 3.10+
- Node.js 20+ (for the frontend dashboard)
- PostgreSQL 15+ with the pgvector extension
- Redis 5.0+

## 1. Install dependencies

```bash
# Backend (all runtime + dev/test deps in one file)
pip install -r requirements.txt

# Frontend (uses pnpm 9)
cd frontend && pnpm install
```

## 2. Configure environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Required variables:

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trading_control

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM (Groq is default; Anthropic is optional fallback)
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
ANTHROPIC_API_KEY=your_anthropic_key   # optional

# Alpaca (paper trading)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true

# App
FRONTEND_URL=http://localhost:3000
LOG_LEVEL=INFO
ENABLE_SIGNAL_SCHEDULER=false
BROKER_MODE=paper
```

## 3. Run the backend

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

- API docs (Swagger): `http://localhost:8000/docs`
- Health check: `GET http://localhost:8000/api/health`

## 4. Run the frontend

```bash
cd frontend
pnpm dev
# Opens at http://localhost:3000
```

## 5. Run tests

CI runs two separate commands — always mirror this locally:

```bash
# Unit tests (mirrors CI step 1)
pytest tests/core tests/api -v --tb=short

# Integration tests (mirrors CI step 2)
pytest tests/integration -v --tb=short

# Agent tests (local only — not in CI, but catches regressions before push)
pytest tests/agents -v --tb=short
```

**Never run `pytest tests/` as a single command** — the CI pipeline runs them split, so ordering-sensitive failures only surface when you run the subsets separately.

## 6. Lint and format

```bash
# Fix all lint issues
ruff check . --fix

# Format
ruff format .

# Verify CI-ready (run this before pushing)
ruff check . --fix && ruff format --check . && ruff check . --select=E9,F63,F7,F82
```

## Common issues

| Problem | Fix |
|---|---|
| `DATABASE_URL is required` | Set a PostgreSQL connection string in `.env` |
| DB connection fails | Verify PostgreSQL is running and pgvector is installed |
| Redis connection fails | Verify Redis is running on the configured port |
| Alpaca errors | Check API key and ensure `ALPACA_PAPER=true` for paper mode |
| CORS errors in dev | Set `FRONTEND_URL=http://localhost:3000` in `.env` |

## Adding a new agent

1. Create `api/services/agents/your_agent.py` using the template in `CLAUDE.md`.
2. Add a row to `agent_pool` seed migration with a hardcoded UUID.
3. Register it in `api/main.py` agent initialization.
4. Add tests in `tests/agents/test_your_agent.py`.
5. Update `docs/architecture.md` stream chain table.
6. Update `CHANGELOG.md`.

## Adding a new API endpoint

1. Create or update a route file in `api/routes/`.
2. Register the router in `api/main.py`.
3. Add tests in `tests/api/test_{router_name}.py`.
4. Update the Fern definition in the `fern-support/matthew` repo.
5. Update `CHANGELOG.md`.

For dashboard, websocket hydration, or metrics read endpoints, add the memory path first:

- Check `is_db_available()` before creating `AsyncSessionFactory()` or accepting an `AsyncSession`.
- Return from `get_runtime_store()` with `source: "in_memory"` when the DB is unavailable.
- Add a regression test that sets `set_db_available(False)` and asserts the DB session factory was not called.

## Logging standards

Always use `log_structured()` — never `print()` or `logger.*`:

```python
from api.observability import log_structured

# Info
log_structured("info", "order created", symbol="BTC/USD", qty=0.1)

# Errors — always use exc_info=True
try:
    risky_operation()
except Exception:
    log_structured("error", "operation failed", exc_info=True, context=data)
```
