# Deployment Guide

## Production stack

| Service | Platform | Notes |
|---|---|---|
| Backend API | Render (Web Service) | `api.main:app` via gunicorn + uvicorn workers |
| Frontend | Vercel | Next.js 14, auto-deploys from `main` |
| Database | Render PostgreSQL | pgvector extension required |
| Redis | Render Redis | Used for streams, pub/sub, and agent heartbeats |

## Required environment variables

Set all of these in your Render web service dashboard:

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/trading_control

# Redis
REDIS_URL=redis://host:6379/0

# LLM
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
ANTHROPIC_API_KEY=your_anthropic_key   # optional fallback

# Alpaca (paper trading)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true
MARKET_DATA_PROVIDER=alpaca

# App
FRONTEND_URL=https://trading-control-khaki.vercel.app
BROKER_MODE=paper
LOG_LEVEL=INFO
ENABLE_SIGNAL_SCHEDULER=true

# Agent thresholds
SIGNAL_EVERY_N_TICKS=10
GRADE_EVERY_N_FILLS=5
IC_UPDATE_EVERY_N_FILLS=10
REFLECT_EVERY_N_FILLS=10
REFLECTION_TRADE_THRESHOLD=20

# LLM limits
LLM_TIMEOUT_SECONDS=15
LLM_MAX_RETRIES=2
LLM_FALLBACK_MODE=skip_reasoning
ANTHROPIC_DAILY_TOKEN_BUDGET=5000000
ANTHROPIC_COST_ALERT_USD=5.0
MAX_CONSUMER_LAG_ALERT=5000
```

## Backend deployment checklist

1. Provision PostgreSQL 15+ and enable the pgvector extension.
2. Provision Redis 5.0+.
3. Set all required environment variables in Render.
4. Deploy with start command: `gunicorn api.main:app -k uvicorn.workers.UvicornWorker`.
5. Verify startup passes DB connectivity and schema initialization.
6. Run smoke checks (see below).

## Frontend deployment checklist

1. Connect the `frontend/` directory to Vercel.
2. Set `NEXT_PUBLIC_API_URL` to your Render backend URL.
3. Ensure Render's `FRONTEND_URL` allows your Vercel origin (CORS).
4. Verify the dashboard loads at `/dashboard`.

## Post-deploy smoke checks

```bash
# Health check
curl -sS https://<backend-host>/api/health | jq .

# Root
curl -sS https://<backend-host>/

# Agent status
curl -sS https://<backend-host>/api/dashboard/agents/status | jq .

# System metrics
curl -sS https://<backend-host>/api/dashboard/system/metrics | jq .
```

Expected: all return 200 with valid JSON.

## Database schema

The schema is initialized automatically on startup. If you need to run migrations manually:

```bash
alembic upgrade head
```

Schema version: **v3**. Verify with:

```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs WHERE schema_version='v3';"
```

## Redis stream verification

```bash
redis-cli -u $REDIS_URL xlen market_ticks   # > 0 within 30s of poller starting
redis-cli -u $REDIS_URL xlen signals         # > 0 shortly after
redis-cli -u $REDIS_URL xlen decisions       # > 0 shortly after
redis-cli -u $REDIS_URL keys "agent:status:*"
```
