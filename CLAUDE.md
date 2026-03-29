# CLAUDE.md — Trading Control

This file is read by Claude Code at the start of every session.
Follow every rule here without exception. Do not skip sections.
Do not ask permission to follow these rules — just follow them.

---

## Project Overview

Trading Control is an event-driven algorithmic trading platform.

- **Backend**: FastAPI (Python 3.10+) on Render
- **Frontend**: Next.js 14 (TypeScript) on Vercel  
- **Database**: PostgreSQL on Render (schema version v2)
- **Cache/Streams**: Redis on Render
- **Market Data**: Alpaca API (paper trading mode)
- **Repo**: https://github.com/SamuelMatthew95/trading-control
- **Live App**: https://trading-control-khaki.vercel.app/dashboard

---

## How to Start Every Session

Before writing a single line of code, always do this:

1. Run `git status` — know what is already changed
2. Run `git log --oneline -10` — know what was recently done
3. Read any file you are about to change — never edit blind
4. Run `pytest tests/ -v --tb=short` — know the baseline test state
5. Check for the specific files relevant to the task

Never assume a file's contents from memory. Always read it first.

---

## Architecture: How the System Works

### Data Flow (memorize this)

```
Alpaca API
    ↓ (every 5 seconds)
price_poller worker (Render worker service — NOT inside FastAPI)
    ↓ writes three things simultaneously:
    ├── Redis SET prices:{symbol}  (cache, TTL 30s) → REST endpoint reads this
    ├── Redis XADD market_events  (stream) → SIGNAL_AGENT reads this
    └── Redis PUBLISH price_updates (pub/sub) → SSE endpoint broadcasts this
    └── Postgres UPSERT prices_snapshot → REST fallback when Redis miss
         ↓
SIGNAL_AGENT (reads market_events stream)
    ↓ XADD signals stream
REASONING_AGENT (reads signals stream)
    ↓ XADD decisions stream
GRADE_AGENT (reads decisions stream)
    ↓ XADD graded_decisions stream
    ├── IC_UPDATER
    ├── REFLECTION_AGENT  
    ├── STRATEGY_PROPOSER
    └── NOTIFICATION_AGENT
         ↓
Frontend (Next.js)
    ├── GET /api/v1/prices on mount → instant load from Redis cache
    ├── EventSource /api/v1/prices/stream → live SSE updates
    └── GET /api/v1/agents/status every 10s → agent health
```

### The 7 Agents

| Agent | Reads From | Writes To | Purpose |
|-------|-----------|-----------|---------|
| SIGNAL_AGENT | market_events | signals | Detect momentum, crossings |
| REASONING_AGENT | signals | decisions | Rule-based BUY/SELL/HOLD |
| GRADE_AGENT | decisions | graded_decisions | Score decision quality |
| IC_UPDATER | graded_decisions | Postgres strategies | Update investment context |
| REFLECTION_AGENT | graded_decisions | Postgres vector_memory | Write semantic memory |
| STRATEGY_PROPOSER | graded_decisions | Postgres strategies | Propose strategy updates |
| NOTIFICATION_AGENT | graded_decisions | Postgres events + alerts | Fire trade alerts |

### Key Rule: Streams vs Pub/Sub

- **Redis Streams (XADD/XREAD)**: durable, agents use these, messages persist
- **Redis Pub/Sub (PUBLISH/SUBSCRIBE)**: ephemeral, browser SSE uses this only
- Never replace a stream with pub/sub. Never use pub/sub for agent communication.

---

## Database Schema (canonical — never deviate)

Schema version: `v2`  
Every INSERT to a versioned table must include `schema_version='v2'` and `source='<service_name>'`.

### Core Tables
- `strategies` — strategy definitions and config
- `orders` — all trading orders with lifecycle state
- `positions` — current exposure per strategy/symbol
- `trade_performance` — realized PnL and analytics
- `events` — durable domain events (event sourcing)
- `processed_events` — exactly-once deduplication
- `audit_log` — immutable change history
- `schema_write_audit` — schema compliance tracking

### Agent Tables
- `agent_pool` — registry of all 7 agents (seeded with hardcoded UUIDs)
- `agent_runs` — every agent execution with input/output
- `agent_logs` — step-level logs per run with trace_id
- `agent_grades` — quality scores per run
- `vector_memory` — 1536-dim embeddings for semantic search

### Analytics Tables
- `system_metrics` — operational metrics time series
- `prices_snapshot` — latest price per symbol (REST fallback)
- `agent_heartbeats` — latest agent status (dashboard display)

### Migration Rules
- Never DROP TABLE or DROP COLUMN on existing tables
- Never ALTER a column that already has data
- Only ADD new tables or ADD new nullable columns with safe defaults
- Always run `alembic upgrade head --sql` dry run before applying
- Migration chain must be linear: check `down_revision` in each file

---

## Coding Rules

### Python (Backend)

**Async**
- All database calls must be async (use asyncpg or SQLAlchemy async)
- All Redis calls must be async (use aioredis or redis-py async)
- Never use `time.sleep()` — use `await asyncio.sleep()` only for the 5s poll interval
- No defensive sleeps anywhere. If something fails, log it and continue or raise.

**Error Handling**
- Never swallow exceptions silently
- Every except block must log with context before continuing
- Use `logger.error` for failures, `logger.warning` for degraded operations
- Never `except Exception: pass` 
- Fail fast on startup (bad config, missing env vars) — let Render restart the process

**Logging — every log line must follow this format:**
```
[service_name] action: key=value key=value — outcome
```
Examples:
```python
logger.info("[price_poller] BTC/USD fetched: price=65234.50 change=+120.30 pct=+0.18% ts=1234567890")
logger.info("[price_poller] cycle complete: symbols=6 duration_ms=340")
logger.warning("[SIGNAL_AGENT] duplicate skipped: msg_id=1234-0 already in processed_events")
logger.error("[GRADE_AGENT] agent_runs write failed: run_id=xyz error=UniqueViolation — event still processed")
logger.info("[REASONING_AGENT] decision: symbol=BTC/USD action=BUY confidence=0.75 trace_id=abc-123")
```
Rules:
- Always include `[service_name]` prefix
- Always include `trace_id` when processing an agent event
- Always include `symbol` when processing price/signal data
- Always include `msg_id` when reading from a Redis stream
- Always include the outcome after the dash
- Use `key=value` pairs for machine-readable fields

**Schema Compliance**
- Every INSERT to a versioned table includes `schema_version='v2'` and `source` 
- Every agent run creates a row in `agent_runs` before starting
- Every agent run updates `agent_runs` on completion or failure
- `trace_id` must be propagated from the triggering event — never generate a new one mid-chain

**Exactly-Once Processing**
Every agent must check `processed_events` before processing any stream message:
```python
exists = await db.fetchval(
    "SELECT 1 FROM processed_events WHERE msg_id = $1", msg_id
)
if exists:
    logger.warning(f"[{agent_name}] duplicate skipped: msg_id={msg_id}")
    continue
# process the event
await db.execute(
    "INSERT INTO processed_events (msg_id, stream) VALUES ($1, $2) ON CONFLICT DO NOTHING",
    msg_id, stream_name
)
```

**Idempotency Keys**
- Must use `trace_id` not `timestamp` in idempotency keys
- Format: `f"{event_type}-{symbol}-{trace_id}"` 
- Never use `f"{event_type}-{symbol}-{int(time.time())}"` — breaks under load

**Timeouts**
- All external API calls must have a timeout
- Alpaca fetches: `async with asyncio.timeout(8):` 
- Database queries: set statement_timeout in connection config
- Never let an external call block the event loop indefinitely

### TypeScript (Frontend)

**Data Fetching**
- Always call `GET /api/v1/prices` on mount — never wait for SSE for initial data
- Use `EventSource` for live price updates — never WebSocket for prices
- Always show a skeleton loader while fetching — never show "--"
- Always handle the error state — never leave the UI in a broken silent state

**SSE Pattern**
```typescript
// correct pattern — always follow this
useEffect(() => {
  fetch(`${API_URL}/api/v1/prices`)
    .then(r => r.json())
    .then(setPrices)
    .catch(err => logger.error('prices fetch failed', err))

  const es = new EventSource(`${API_URL}/api/v1/prices/stream`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data)
    setPrices(prev => ({ ...prev, [data.symbol]: data }))
  }
  es.onerror = () => {
    // log it — reconnect is automatic with EventSource
    console.warn('[prices] SSE disconnected, browser will retry')
  }
  return () => es.close()
}, [])
```

**Environment Variables**
- Never hardcode any URL or credential
- All backend URLs use `NEXT_PUBLIC_API_URL` 
- Never commit `.env.local` — only `.env.local.example` 

**Component Rules**
- Price cards must show: symbol, price (formatted $XX,XXX.XX), change amount, change %, freshness dot
- Agent matrix must show: name, status badge, last event, time since last seen, event count
- Connection indicator: green "Live" / amber "Reconnecting..." / red "Offline"

---

## What Never Changes

These are hard constraints. Do not touch them without explicit discussion:

1. The price poller is a separate Render worker service — never move it into FastAPI lifespan
2. Agents use Redis Streams (XADD/XREAD) — never replace with pub/sub
3. Frontend uses SSE (EventSource) — never revert to WebSocket for prices
4. Every agent run writes to `agent_runs` — never skip this
5. `trace_id` propagates through the entire chain — never reset it mid-pipeline
6. `schema_version='v2'` on every versioned INSERT — never omit it
7. Migrations never DROP or ALTER existing columns with data
8. No hardcoded UUIDs in application code — always query `agent_pool` by name
9. No defensive sleeps anywhere in the codebase
10. No fake or random price data — always use real Alpaca API

---

## Before Every Commit Checklist

Run all of these. Do not commit if any fail:

```bash
# 1. Tests must pass
pytest tests/ -v --tb=short

# 2. No unexpected sleeps
grep -rn "asyncio.sleep\|time.sleep" . --include="*.py" \
  | grep -v "sleep(5)" | grep -v ".pyc"
# expected: empty (only the poll interval is allowed)

# 3. No hardcoded URLs
grep -rn "onrender.com\|vercel.app\|localhost:8000" . \
  --include="*.ts" --include="*.tsx" --include="*.py" \
  | grep -v ".env" | grep -v "CLAUDE.md"
# expected: empty

# 4. Schema version present on new inserts
# manually verify any new INSERT includes schema_version='v2'

# 5. No print statements left in Python
grep -rn "^[[:space:]]*print(" . --include="*.py" | grep -v ".pyc" | grep -v "test_"
# expected: empty

# 6. TypeScript compiles
cd frontend && npx tsc --noEmit

# 7. Migrations dry run clean
alembic upgrade head --sql 2>&1 | grep -E "DROP TABLE|DROP COLUMN"
# expected: empty
```

---

## Running Locally

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your values
alembic upgrade head
uvicorn api.main:app --reload --port 8000

# Price poller (separate terminal)
python -m api.workers.price_poller

# Frontend (separate terminal)
cd frontend
npm install
cp .env.local.example .env.local  # set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev

# Tests
pytest tests/ -v --tb=short
```

## Key Verification Commands

```bash
# Confirm poller is writing to Redis
redis-cli keys "prices:*"                    # should show 6 keys
redis-cli xlen market_events                 # should be > 0 and growing

# Confirm agents are firing
redis-cli xlen signals                       # > 0 within 30s of poller starting
redis-cli xlen decisions                     # > 0 shortly after
redis-cli xlen graded_decisions              # > 0 shortly after
redis-cli keys "agent:status:*"              # should show all 7 agents

# Confirm DB is healthy
psql $DATABASE_URL -c "SELECT agent_name, status, event_count, last_seen FROM agent_heartbeats;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs WHERE status='completed';"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM processed_events;"

# Confirm endpoints
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/prices | python3 -m json.tool
curl -s http://localhost:8000/api/v1/agents/status | python3 -m json.tool
curl -N --max-time 10 http://localhost:8000/api/v1/prices/stream
```

---

## Common Mistakes to Avoid

| Wrong | Right |
|-------|-------|
| Polling loop inside FastAPI lifespan | Separate Render worker service |
| `await asyncio.sleep(3)` on error | Log the error and continue |
| `idempotency_key = f"signal-{symbol}-{ts}"` | `f"signal-{symbol}-{trace_id}"` |
| `trace_id = uuid4()` in each agent | Extract from upstream event payload |
| `embedding = [0.0] * 1536` without cast | `array_fill(0::real, ARRAY[1536])::vector` |
| `gen_random_uuid()` in seed migration | Hardcoded UUIDs in seed |
| WebSocket for price streaming | SSE with EventSource |
| Showing "--" while prices load | Skeleton loader |
| `except Exception: pass` | Log with context and continue or raise |
| `PUBLISH` for agent communication | `XADD` to named stream |

---

## When Something Is Broken

1. Check Render logs for the `trading-price-poller` worker first
   — if the poller is down, everything downstream is starved
2. Run `redis-cli xlen market_events` — if 0 or not growing, poller is broken
3. Run `redis-cli xlen signals` — if 0 but market_events has data, SIGNAL_AGENT is broken
4. Check `agent_runs` table for `status='failed'` rows — read the `error_message` 
5. Check `processed_events` table — if it has no rows, exactly-once is not working
6. Check `agent_heartbeats` — `last_seen` timestamp tells you when each agent last fired

---

## After Every Task

Before ending any session or marking a task complete, update CHANGELOG.md.
Add an entry at the top under today's date using this format:

## [YYYY-MM-DD] — short title of what was done

### Changed
- what file was changed and why

### Added  
- what new files or features were added

### Fixed
- what bugs were fixed, what the root cause was

### Verified
- what tests were run, what manual checks were done, what the results were

### Remaining / Known Issues
- anything not completed, any known risks, anything the next session should check first

Do not write vague entries like "updated agent code".
Write specific entries like "fixed trace_id propagation in reasoning_agent.py —
was generating new uuid4() instead of extracting from upstream event payload".

---

## API Documentation (Fern)

Live docs: https://matthew.docs.buildwithfern.com/
Fern source: private GitHub repo — accessible via GitHub MCP tool.

### Reading the docs
When you need to understand current API structure, use the GitHub MCP
tool to read the Fern definition files from the private repo before
making any endpoint changes.

### Keeping docs in sync
When you add or change any API endpoint, you must:
1. Make the code change in this repo
2. Use the GitHub MCP tool to read the current Fern definition
3. Update the Fern definition file in the private repo to match
4. Commit both changes — code change here, docs change in Fern repo
5. Note both changes in CHANGELOG.md

Never merge a PR that adds or changes an endpoint without a matching
Fern definition update.

### What counts as a docs change
- New endpoint added → add to Fern definition
- Endpoint response shape changed → update type definition
- Endpoint deprecated → mark deprecated, do not delete
- New query parameter → add to parameter definition
- Error response changed → update error type

### Fern repo details
- Repo name: fern-support/matthew
- Definition files location: [add path once confirmed e.g. fern/definition/]
- To verify changes published: check https://matthew.docs.buildwithfern.com/

---

## Current Status

- [x] Price poller running as separate Render worker
- [x] REST + SSE endpoints for prices
- [x] Agent pipeline connected: market_events → signals → decisions → graded_decisions
- [x] Exactly-once processing via processed_events table
- [x] trace_id propagation through agent chain
- [x] agent_runs and agent_logs writes on every run
- [x] Frontend using REST on mount + SSE for live updates
- [x] All canonical schema tables created
- [ ] Real embedding model wired into REFLECTION_AGENT (currently zero vector placeholder)
- [ ] LLM reasoning in REASONING_AGENT (currently rule-based)
- [ ] Paper trade execution in IC_UPDATER
- [ ] Slack/email notifications in NOTIFICATION_AGENT
