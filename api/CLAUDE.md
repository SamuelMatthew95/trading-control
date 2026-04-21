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

### Dict key access — use FieldName, never raw strings
```python
# ❌ WRONG
side = data.get("side")
trace = event["trace_id"]

# ✅ RIGHT
side = data.get(FieldName.SIDE)
trace = event[FieldName.TRACE_ID]
```
Missing a field? Add it to `class FieldName(StrEnum)` first, then reference it.

## DB access
- Raw SQL via `text()` + `RETURNING id` for agent_runs/events (INTEGER pks)
- ORM via SQLAlchemy models for orders/positions
- Sessions: `async with get_async_session() as session:`

## Key services
- `api/services/agent_heartbeat.py` — shared heartbeat (Redis + Postgres)
- `api/services/safe_writer.py` — idempotent DB writes
- `api/observability.py` — `log_structured()` only, no `logger.*`
