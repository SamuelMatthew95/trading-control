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
