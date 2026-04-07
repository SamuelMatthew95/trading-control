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

## Critical Anti-Patterns (NEVER Do These)
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

## CI/CD Commands (Must Pass)
```bash
ruff check . --fix                    # Linting
ruff format --check .                 # Formatting  
ruff check . --select=E9,F63,F7,F82   # Critical errors
pytest tests/ -v --tb=short          # All tests pass
```

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

## Additional Rules (Always Loaded)
@./.claude/rules/memory-trading.md     # Alpaca trading specifics
@./.claude/rules/memory-agents.md      # Agent hand-off protocols  
@./.claude/rules/memory-logging.md     # Trace ID & logging standards
@./.claude/rules/memory-cicd.md       # CI/CD patterns and fixes
