# CI/CD Patterns & Common Fixes
# Memory File: CI/CD
# Version: v2.0
# Last Updated: 2026-04-13

## How CI Works (GitHub Actions — backend-ci.yml)

CI runs on Python 3.10 AND 3.11 in parallel. Three steps:
```
Step 1 — Lint:       ruff check . --fix
                     ruff format --check .
                     ruff check . --select=E9,F63,F7,F82

Step 2 — Unit:       pytest tests/core tests/api -v

Step 3 — Integration: pytest tests/integration -v
```

`tests/agents/` is NOT in CI (those tests run locally only via verify_ci.sh).

## Pre-push Verification Script

```bash
./scripts/verify_ci.sh          # full (matches CI exactly + agent tests)
./scripts/verify_ci.sh --fast   # skip integration (inner loop)
```

**Always run this script before pushing.** Running `pytest tests/` alone won't
catch ordering-sensitive failures that only appear under the CI split-subset order.

---

## Known Failure Patterns

### 1 — Test Pollution via Global InMemoryStore

**What breaks:** A test that expects an empty store gets data from a previous test.
**Root cause:** `_db_available = False` by default. Any test that calls `agent.process()`
(e.g. `SignalGenerator.process()`) writes to the module-level `InMemoryStore`. That state
survives into the next test.

**The fix — autouse fixture in `tests/conftest.py` (already present):**
```python
@pytest.fixture(autouse=True)
def _reset_runtime_state():
    set_runtime_store(InMemoryStore())
    set_db_available(False)
```
Every test starts with a clean store and `is_db_available() == False`.

**Rules:**
- NEVER call `set_db_available(True)` globally in a test — use monkeypatch on the module
- NEVER assume the store is empty without calling `set_runtime_store(InMemoryStore())` first
- If your new test calls `agent.process()` and the next test fails with unexpected store
  data — this is why. The autouse fixture handles it, but double-check you didn't call
  `set_db_available(True)` without resetting after.

```python
# ❌ WRONG — leaks True into subsequent tests
set_db_available(True)
await sg.process(data)

# ✅ RIGHT — isolated to this module call only
monkeypatch.setattr("api.services.signal_generator.is_db_available", lambda: True)
await sg.process(data)
```

---

### 2 — B008: Function Call in Default Argument

```python
# ❌ WRONG
async def endpoint(svc=Depends(get_service)):

# ✅ RIGHT
from typing import Annotated
async def endpoint(svc: Annotated[Service, Depends(get_service)]):
```

---

### 3 — B904: Raise Without From

```python
# ❌ WRONG
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

# ✅ RIGHT
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e)) from None
```

---

### 4 — F821: Undefined Name (Missing Import)

ruff -select=F82 catches this. Common case: `Annotated` or a service type used
in a type hint without importing it.

```python
# ❌ WRONG — Annotated used but not imported
svc: Annotated[MyService, Depends(get_svc)]

# ✅ RIGHT
from typing import Annotated
```

---

### 5 — Logging Pattern Violations

```python
# ❌ WRONG — CI won't flag this but breaks structured log parsing
log_structured("error", "failed", error=str(exc))

# ✅ RIGHT
log_structured("error", "failed", exc_info=True)
```

---

### 6 — Redis Keyword Argument Incompatibility (FakeRedis)

```python
# ❌ WRONG — fails with FakeRedis in tests
await redis.xgroup_create(stream, group, id="$", mkstream=True)

# ✅ RIGHT — positional arg works everywhere
await redis.xgroup_create(stream, group, "$", mkstream=True)
```

---

### 7 — DEFAULT_AGENTS Keys Not Matching ALL_AGENT_NAMES

`write_heartbeat()` writes to the store with SCREAMING_SNAKE_CASE agent name constants.
`InMemoryStore.DEFAULT_AGENTS` keys must match those constants exactly.

```python
# ❌ WRONG — ghost idle agents appear next to active agents in the dashboard
DEFAULT_AGENTS = {"signal_generator": {"status": "idle"}, ...}

# ✅ RIGHT — keys are the same constants heartbeat uses
from api.constants import AGENT_SIGNAL, ...
DEFAULT_AGENTS = {AGENT_SIGNAL: {"status": "idle"}, ...}
```

Guardrail test: `tests/agents/test_in_memory_persistence.py::test_default_agents_keys_match_all_agent_names`

---

### 8 — is_db_available() Routing Not Consolidated

Every `if is_db_available():` block must live inside a dedicated private method
(`_begin_run`, `_persist_run`, `_persist_vector`, etc.), NOT inline inside `process()`.
`process()` must be zero-conditional — it just calls the unified routing method.

```python
# ❌ WRONG — routing scattered inline
async def process(self, data):
    if is_db_available():
        await self._db_write(...)
    else:
        store.add_event(...)

# ✅ RIGHT — process() stays clean
async def process(self, data):
    await self._persist_result(data)   # routing hidden inside

async def _persist_result(self, data):
    if is_db_available():
        await self._db_write(data)
    else:
        get_runtime_store().add_event(...)
```

---

### 9 — Missing source Column in DB Writes

Migrations 20260407 added `source VARCHAR(64) NOT NULL` to `agent_runs`, `agent_logs`,
`agent_grades`. All INSERTs must include it or the DB will reject the row.

```python
# ❌ WRONG — missing source
await session.execute(text("INSERT INTO agent_runs (trace_id, ...) VALUES (...)"), {...})

# ✅ RIGHT
await session.execute(text("INSERT INTO agent_runs (trace_id, source, ...) VALUES (...)"),
    {"source": AGENT_SIGNAL, ...})
```

---

## Code Smell Checks (run before pushing)

```bash
# No raw print() calls in api/
grep -rn "^[[:space:]]*print(" api/ --include="*.py"

# No old logger.* calls in api/
grep -rn "logger\." api/ --include="*.py" | grep -v "= logging.getLogger"

# No hardcoded agent name strings (should all be constants)
grep -rn '"signal_generator"\|"reasoning"\|"grade_agent"' api/ --include="*.py"
```

## Test File Naming Conventions

```
tests/agents/test_{agent_name}.py     # per-agent
tests/api/test_{router_name}.py       # per API router
tests/core/test_{module_name}.py      # core logic
tests/integration/test_{flow}.py      # end-to-end flows
```

Every bug fix must include a regression test that would have caught the bug.
