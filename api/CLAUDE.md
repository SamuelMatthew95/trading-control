# API — FastAPI Backend Context

> Lazy-loaded: only active when working in `api/`

## Route Patterns
```python
# CORRECT — Annotated Depends (avoids B008 lint error)
from typing import Annotated
async def endpoint(
    service: Annotated[MyService, Depends(get_service)]
): ...
```

## Error Handling
```python
except Exception as e:
    log_structured("error", "operation failed", exc_info=True)
    raise HTTPException(status_code=500, detail=str(e)) from None
```

## Constants (api/constants.py)
All Redis keys, TTLs, agent names, AND event-payload field names live here — never hardcode strings.
```python
from api.constants import (
    REDIS_KEY_PRICES, REDIS_KEY_KILL_SWITCH, REDIS_KEY_IC_WEIGHTS,
    REDIS_PRICES_TTL_SECONDS, REDIS_IC_WEIGHTS_TTL_SECONDS,
    AGENT_SIGNAL, AGENT_REASONING, ALL_AGENT_NAMES,
    FieldName,  # StrEnum for all payload/DB-row dict keys
)
```

### What belongs in `api/constants.py` (placement rule)

A value belongs in `api/constants.py` when EITHER is true:
- it is referenced by **2+ modules**, or
- it is a **cross-module contract** — Redis keys, stream names, agent names,
  `FieldName` keys, schema versions, shared thresholds / limits / dimensions.

A value may stay **module-local** only when it is owned by a dedicated
single-purpose module — e.g. LLM prompt text in `services/agents/prompts.py`,
DB-bootstrap internals in `database.py`, `schema_version.py`. A service or
route file is NOT such a module: never define a bare `MAGIC = 1234` constant
there — move it to `api/constants.py` and import it.

```python
# ❌ WRONG — magic config defined in a service file
# api/services/metrics_aggregator.py
CRITICAL_LAG_MS = 5000

# ✅ RIGHT — defined in api/constants.py, imported where used
from api.constants import CRITICAL_LAG_MS
```

### Imports — top of file only (ENFORCED BY CI: ruff `PLC0415`)

Every `import` goes at the top of the module. Inline imports inside a
function are allowed ONLY to (a) break a circular import or (b) lazy-load an
optional dependency — and each such site MUST carry `# noqa: PLC0415`.

```python
# ❌ WRONG — stdlib / non-circular import buried in a function
def handler():
    import json
    from api.database import AsyncSessionFactory

# ✅ RIGHT — at module top
import json
from api.database import AsyncSessionFactory

# ✅ ALLOWED — circular-import break, explicitly marked
def handler():
    from api.services.redis_store import get_redis_store  # noqa: PLC0415
```

Gotcha: moving a name from an inline import to the module top changes how
tests must patch it. `monkeypatch.setattr("api.database.AsyncSessionFactory", …)`
only works while the import is lazy. Once it is a top-level import, patch the
name **where it is looked up** — `monkeypatch.setattr(route_module, "AsyncSessionFactory", …)`.

### Dict key access — use FieldName, never raw strings (ENFORCED BY CI)

Every event-payload / DB-row / Redis-message dict access must go through
`FieldName`. Raw string keys silently break when a field renames; `FieldName`
turns drift into an ImportError the type checker catches.

```python
# ❌ WRONG — raw strings
side = data.get("side")
trace = event["trace_id"]
payload = {"symbol": sym, "side": "buy", "trace_id": tid}

# ✅ RIGHT — FieldName (StrEnum; serializes to the same string)
side = data.get(FieldName.SIDE)
trace = event[FieldName.TRACE_ID]
payload = {FieldName.SYMBOL: sym, FieldName.SIDE: "buy", FieldName.TRACE_ID: tid}
```

**Enforced by `tests/core/test_field_name_guardrails.py`** — an AST scan that
fails CI when any file on the `CLEAN_FILES` allowlist re-introduces a raw
string FieldName key. When you add a new file to the sweep, append it to
`CLEAN_FILES` so the guardrail locks it in.

Missing a field? Add it to `class FieldName(StrEnum)` in `api/constants.py`
first (member name MUST equal value in uppercase — `FOO = "foo"`), then
reference `FieldName.FOO` everywhere you read/write that payload key.

**Legitimate exceptions** (keep as raw strings):
- **SQL bind parameters**: keys in the dict passed as the 2nd arg to
  `session.execute(text("... :name ..."), {...})` must match the `:name`
  placeholders in the SQL string. Do NOT use `FieldName` there.
- **SQLAlchemy `.values(col=...)` and `set_={...}` kwargs**: column names,
  not payload keys. Leave alone.
- **Kwargs in function calls** like `log_structured("info", "msg", symbol=x)`:
  the `symbol=x` is a keyword argument, not a dict key. Leave alone.

## DB access
- Raw SQL via `text()` + `RETURNING id` for agent_runs/events (INTEGER pks)
- ORM via SQLAlchemy models for orders/positions
- Sessions: `async with get_async_session() as session:`

## Key services
- `api/services/agent_heartbeat.py` — shared heartbeat (Redis + Postgres)
- `api/services/safe_writer.py` — idempotent DB writes
- `api/observability.py` — `log_structured()` only, no `logger.*`

## Learning Endpoints — DB-Down State (InMemoryStore)

`/learning/*` endpoints operate in two modes controlled by `is_db_available()`.

### DB up
Queries hit PostgreSQL: `trade_evaluations`, `reflections`, `strategies`.
If `trade_evaluations` is empty (migration ran, no `STREAM_TRADE_COMPLETED`
events yet), `agent_grades` is bridged into the same response shape via
`_db_grades_as_trades(session, text, limit, offset)`.

### DB down — InMemoryStore IS the state
`InMemoryStore` is the authoritative store, not a degraded fallback.
Agents write to it continuously while the DB is unavailable:

| Agent | Writes to InMemoryStore |
|-------|------------------------|
| GradeAgent | `store.add_grade(payload)` → `grade_history` |
| LearningPipeline | `store.add_trade_evaluation(payload)` → `trade_evaluations` |
| ReflectionAgent | `store.add_reflection(payload)` → `reflections` |
| StrategyProposer | `store.add_strategy(payload)` → `strategies` |

If `trade_evaluations` is empty in memory mode (GradeAgent ran but no
`STREAM_TRADE_COMPLETED` events processed yet), `grade_history` is bridged
via `_mem_grades_as_trades(store, limit, offset)` so the UI shows real data.

### Response `mode` field
Every `/learning/*` response includes `"mode": "db"` or `"mode": "memory"`.
The UI uses this to surface a banner when running in DB-down mode.

### Rules
- Never call `_mem_grades_as_trades` from the DB-up path — it reads InMemoryStore.
- Never call `_db_grades_as_trades` from the DB-down path — it executes SQL.
- Both helpers return `(list[dict], int)` — same shape, swappable.
