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

## Optional: Local GPU inference (LM Studio)

The backend tries LM Studio first on every LLM call and falls back to the cloud provider transparently. This is entirely opt-in — leave all `LM_STUDIO_*` vars unset (default) to run cloud-only.

### Render + LM Link (Tailscale)

Render cannot access your home GPU directly. Use **LM Link** (Tailscale) to create an encrypted peer-to-peer tunnel:

1. Install Tailscale on your home GPU machine and on your Render instance (via build command or sidecar).
2. `tailscale up` on both — log in to the same Tailscale account.
3. Note the Tailscale IP of your GPU machine (`tailscale ip -4`).
4. Set these env vars in the Render dashboard:

```env
# ── Local GPU via LM Link / Tailscale ───────────────────────────
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=100.64.x.x          # Tailscale IP of your GPU machine
LM_STUDIO_PORT=1234                 # LM Studio default HTTP port
LM_STUDIO_MODEL=lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF
LM_STUDIO_TIMEOUT_SECONDS=90       # raise if your GPU is slow
LM_LINK_ENABLED=true               # flags this as a remote-GPU setup in logs
LM_LINK_DEVICE_NAME=my-gpu-rig    # optional label, appears in startup logs only
# LM_LINK_TOKEN=                   # only needed if a custom proxy sits in front of LM Studio
```

> **LM_LINK_TOKEN** is for an optional authenticating proxy (e.g. nginx + HTTP basic auth) in front of LM Studio. LM Studio itself ignores HTTP `Authorization` headers — leave this unset for a plain Tailscale setup.

### Local (same machine as backend)

If you run the backend locally alongside LM Studio:

```env
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF
LM_STUDIO_TIMEOUT_SECONDS=90
LM_LINK_ENABLED=false
```

### Call capacity

The ReasoningAgent processes one signal at a time (Redis consumer group — one message per loop). That means at most **1 concurrent local inference call** at any moment, which is a natural fit for LM Studio's sequential inference model.

| Model size | Typical latency | Effective calls/min |
|---|---|---|
| 7B Q4 (e.g. Llama-3-8B) | 0.5–3 s | 20–120 |
| 13B Q4 | 2–8 s | 7–30 |
| 30B+ Q4 | 10–60 s | 1–6 |

If LM Studio is slower than `LM_STUDIO_TIMEOUT_SECONDS`, the call falls back to the configured cloud provider and `local_fallback_count` increments in `/llm/health`.

### Verifying local inference is active

```bash
curl -sS https://<backend-host>/api/llm/health | jq '{active_provider, lm_studio_healthy, local_latency_ms, local_fallback_count}'
```

Expected when healthy:
```json
{
  "active_provider": "lmstudio",
  "lm_studio_healthy": true,
  "local_latency_ms": 312,
  "local_fallback_count": 0
}
```

See `docs/local-inference.md` for the full env var reference and `docs/troubleshooting/lm-studio.md` for common failure modes.

---

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

# Dashboard hydration must return JSON even when persistence is in memory mode
curl -sS https://<backend-host>/api/dashboard/state | jq '.source // .mode'
curl -sS https://<backend-host>/api/dashboard/proposals | jq '.source'
curl -sS https://<backend-host>/api/dashboard/agent-instances | jq '.source'
```

Expected: all return 200 with valid JSON.

If Render cannot reach Postgres, dashboard read endpoints should still return `source: "in_memory"` or `mode: "in_memory_fallback"`. They must not log SQLAlchemy DNS/session errors before serving memory data.

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
