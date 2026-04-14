# Trading Control — Core Memory (The "Permanent Seed")

**Project**: Event-driven algorithmic trading platform with 7 specialized agents
**Version**: Schema v3, Python 3.10+, FastAPI + Next.js architecture

## Tech Stack (High-Level)
- **Backend**: FastAPI (Python 3.10+) on Render
- **Frontend**: Next.js 14 (TypeScript) on Vercel  
- **Database**: PostgreSQL 15+ with pgvector extension
- **Cache/Streams**: Redis 5.0+ for agent communication
- **Market Data**: Alpaca API (paper trading mode)

## Core Architecture Principles
1. **Event-Driven**: Agents communicate via Redis Streams only
2. **Traceability**: Every operation carries `trace_id` through entire system
3. **Idempotency**: Orders and events use idempotency keys
4. **Schema Version**: All new writes must use `schema_version='v3'`

## 7-Agent System (Phase 1 Complete)
- **SignalGenerator**: market_ticks → signals
- **ReasoningAgent**: signals → decisions (LLM-powered)
- **ExecutionEngine**: orders → executions  
- **GradeAgent**: executions → performance scores
- **ICUpdater**: performance → factor weights
- **ReflectionAgent**: performance → hypotheses
- **StrategyProposer**: hypotheses → proposals

## Production DB Schema Reality (CRITICAL — Read Before Any INSERT)

The live PostgreSQL DB was created **before** the Alembic migration system.
Several tables have types and constraints that differ from what ORM models assume.

### Tables with INTEGER primary keys (NOT UUID)
```
agent_runs   id INTEGER  nextval('agent_runs_id_seq')
events       id INTEGER  nextval('events_id_seq')
```
**Rule**: Never pass `id` in the INSERT column list for these tables.
Use `RETURNING id` and store the result as `db_run_id` (integer).

```python
# CORRECT pattern for agent_runs / events
result = await session.execute(text("""
    INSERT INTO agent_runs (strategy_id, trace_id, source, schema_version, ...)
    VALUES (:strategy_id, :trace_id, :source, :schema_version, ...)
    RETURNING id
"""), {...})
db_run_id = result.first()[0]  # integer from sequence

# Later UPDATE uses db_run_id (integer), NOT run_id (UUID)
await session.execute(text(
    "UPDATE agent_runs SET status='completed' WHERE id=:id"
), {"id": db_run_id})
```

### Mandatory columns added by migration 20260407
These were absent in the pre-migration schema. All INSERTs must include them:
```
agent_runs   source VARCHAR(64)     — who wrote the row (e.g. AGENT_SIGNAL)
agent_runs   run_type VARCHAR(32)   — defaults to 'analysis' in DB
agent_runs   execution_time_ms INT  — nullable, written in success UPDATE
agent_logs   source VARCHAR(64)     — writer identity
agent_grades source VARCHAR(64)     — writer identity
events       data JSONB             — signal/event payload
events       idempotency_key VARCHAR(255) + UNIQUE INDEX
events       processed BOOLEAN      — defaults to false
events       schema_version VARCHAR(16)
```

### agent_grades NOT NULL constraints
`agent_id` and `agent_run_id` were created NOT NULL in the pre-migration schema.
Migration 20260407 drops both to nullable. `write_grade_to_db()` omits them
(NULL is valid). `signal_generator.py` passes `agent_pool_id or None`.

### Correct INSERT pattern — events (with dedup)
```sql
INSERT INTO events (event_type, entity_type, data, idempotency_key, source, schema_version)
VALUES ('signal.generated', 'signal', :data, :idem_key, :source, :schema_version)
ON CONFLICT (idempotency_key) DO NOTHING
```

### Guardrail tests (always run these)
```
tests/core/test_production_schema_guardrails.py  — source-code inspection
tests/agents/test_signal_generator_db_writes.py  — functional SQL capture
tests/agents/test_signal_generator_schema_fix.py — regression for column names
```

## Critical Anti-Patterns (NEVER Do These)
- ❌ `INSERT INTO agent_runs (id, ...)` → id is INTEGER, never pass UUID; use RETURNING id
- ❌ `"id": run_id` in UPDATE params for agent_runs → use `"id": db_run_id` (integer)
- ❌ `log_structured("error", "msg", error=str(exc))` → Use `exc_info=True`
- ❌ `redis.xgroup_create(stream, group, id="$", mkstream=True)` → Use positional args
- ❌ `async def endpoint(service=Depends(get_service))` → Use `Annotated[Service, Depends(...)]`
- ❌ `raise HTTPException(str(e))` → Add `from None`
- ❌ Missing imports for types → Always import what you use
- ❌ Hardcoded Redis keys anywhere → Use constants from `api/constants.py`
- ❌ Hardcoded TTL values (`ex=30`, `ex=90000`) → Use named constants

## Redis Key Constants (All Redis Keys Live in api/constants.py)
```python
from api.constants import (
    REDIS_KEY_KILL_SWITCH,          # "kill_switch:active"
    REDIS_KEY_KILL_SWITCH_UPDATED_AT, # "kill_switch:updated_at"
    REDIS_KEY_IC_WEIGHTS,           # "alpha:ic_weights"
    REDIS_KEY_PRICES,               # "prices:{symbol}" — use .format(symbol=symbol)
    REDIS_KEY_WORKER_HEARTBEAT,     # "worker:heartbeat"
    REDIS_PRICES_TTL_SECONDS,       # 30s — price cache lifetime
    REDIS_IC_WEIGHTS_TTL_SECONDS,   # 90000s (~25h) — IC weights survive overnight
)
# Prices key usage:
await redis.get(REDIS_KEY_PRICES.format(symbol="BTC/USD"))
pipe.set(REDIS_KEY_PRICES.format(symbol=symbol), payload, ex=REDIS_PRICES_TTL_SECONDS)
# Kill switch usage:
if await redis.get(REDIS_KEY_KILL_SWITCH) == "1": raise RuntimeError("KillSwitchActive")
```

## Shared Heartbeat Module (api/services/agent_heartbeat.py)
All agents write heartbeats via the shared module — never write directly to Redis.
```python
from api.services.agent_heartbeat import write_heartbeat
# Writes to BOTH Redis (AGENT_HEARTBEAT_TTL_SECONDS TTL) and agent_heartbeats Postgres table
await write_heartbeat(redis, AGENT_SIGNAL, last_event="processed BTC/USD tick")
```
Benefit: Postgres `agent_heartbeats` table retains history even after Redis key expiry.

## CI/CD Verification (MANDATORY before every push)

Run these in order — mirrors `.github/workflows/backend-ci.yml` exactly:
```bash
ruff check . --fix
ruff format --check .
ruff check . --select=E9,F63,F7,F82
pytest tests/core tests/api -v --tb=short     # CI "unit tests" step
pytest tests/integration -v --tb=short        # CI "integration tests" step
pytest tests/agents -v --tb=short             # local only — not in CI but catches regressions
```

**Never use `pytest tests/` alone** — CI runs two separate subset commands, so
ordering-sensitive failures only surface when you run them split, not combined.

### Test Isolation Rule (CRITICAL — prevents ghost-state CI failures)
`_db_available` and `get_runtime_store()` are module-level globals. Agents in memory mode
write to the global `InMemoryStore`. Tests that call `agent.process()` without resetting
the store pollute every subsequent test.

`tests/conftest.py` resets both before every test automatically:
```python
@pytest.fixture(autouse=True)
def _reset_runtime_state():
    set_runtime_store(InMemoryStore())
    set_db_available(False)
```
- Never call `set_db_available(True)` globally in a test — monkeypatch the module instead
- Never assume the store is empty without calling `set_runtime_store(InMemoryStore())` first
- See `memory-cicd.md` for the full catalogue of known CI failure patterns

## Agent Name Constants (CRITICAL — Prevents Dashboard Bugs)
All agent names live in `api/constants.py`. NEVER use string literals for agent names.

```python
from api.constants import (
    AGENT_SIGNAL, AGENT_REASONING, ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    AGENT_HEARTBEAT_TTL_SECONDS,   # Redis key TTL — 300s (5 min)
    AGENT_STALE_THRESHOLD_SECONDS, # Show STALE if last_seen > 120s
)
# Agents write heartbeat:
await redis.set(REDIS_AGENT_STATUS_KEY.format(name=AGENT_SIGNAL), ..., ex=AGENT_HEARTBEAT_TTL_SECONDS)
# Dashboard reads:
keys = [REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES]
# Dashboard stale check:
status = "STALE" if age > AGENT_STALE_THRESHOLD_SECONDS else data["status"]
```

Names are SCREAMING_SNAKE_CASE (`SIGNAL_AGENT`, not `SignalGenerator`).

### Heartbeat timing invariant
`AGENT_HEARTBEAT_TTL_SECONDS` > `AGENT_STALE_THRESHOLD_SECONDS` always — otherwise a slow-but-running
agent expires before the dashboard can ever show it as STALE (goes straight to "offline").

## Data Fetch Pipeline (PostgreSQL → API → Frontend)
How the dashboard is hydrated on load / reconnect:

| Data | Source Table | API Layer |
|------|-------------|-----------|
| `orders` | `orders` ORM | `MetricsAggregator.get_raw_snapshot()` |
| `positions` | `positions` ORM | `MetricsAggregator.get_raw_snapshot()` |
| `agent_logs` | `agent_logs` (schema-detected) | `MetricsAggregator.get_raw_snapshot()` |
| `learning_events` | `agent_grades` | `MetricsAggregator.get_raw_snapshot()` |
| `proposals` | `agent_logs WHERE log_type='proposal'` | `MetricsAggregator.get_raw_snapshot()` |
| `trade_feed` | `trade_lifecycle` | `MetricsAggregator.get_raw_snapshot()` |
| `agent_statuses` | Redis `REDIS_AGENT_STATUS_KEY.format(name=n)` | `/dashboard/state` enrichment |
| `ic_weights` | Redis `REDIS_KEY_IC_WEIGHTS` | `/dashboard/state` enrichment |
| `prices` | Redis `REDIS_KEY_PRICES.format(symbol=s)` | `/dashboard/state` enrichment |

REST hydration endpoint: `GET /dashboard/state`
Guardrail tests: `tests/core/test_data_fetch_guardrails.py` + `tests/core/test_agent_constants.py`

## Claude Code Workflow
- **Commits**: One commit per file — never bundle multiple files into one commit
- **Complex tasks**: Start in plan mode (`/plan`) before making changes
- **Context**: Run `/compact` manually when context reaches ~50% usage
- **Personal overrides**: Create `CLAUDE.local.md` at repo root (git-ignored) for local preferences
- **Specialized agents**: Use `.claude/agents/` — `ci-guard` (CI pipeline), `db-migrator` (Alembic), `test-writer` (pytest)
- **Reusable skills**: Use `.claude/skills/` — `run-ci` (full pipeline), `schema-check` (schema audit), `karpathy-guidelines` (think/simplify/surgical/verify), `reverse-prompt` (clarify before coding)
- **XML tags**: Use `<tags>` in prompts with 2+ components — Claude reads them with greater precision
- **Subdirectory context**: `api/CLAUDE.md` and `frontend/CLAUDE.md` load lazily when working in those dirs

## Additional Rules (Always Loaded)
@./.claude/rules/memory-trading.md     # Alpaca trading specifics
@./.claude/rules/memory-agents.md      # Agent hand-off protocols  
@./.claude/rules/memory-logging.md     # Trace ID & logging standards
@./.claude/rules/memory-cicd.md       # CI/CD patterns and fixes
@./.claude/rules/memory-storage.md    # Storage layer rules — Redis KV vs Streams vs Postgres vs InMemoryStore
