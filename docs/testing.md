# Testing Guide

## Test structure

```
tests/
├── core/                              # Foundation & guardrail tests
│   ├── conftest.py                    # autouse InMemoryStore reset
│   ├── fake_session.py                # FakeAsyncSession for DB mocking
│   ├── async_sqlalchemy_mocks.py
│   ├── test_production_schema_guardrails.py  # source-code schema inspection
│   ├── test_field_name_guardrails.py         # FieldName enum CI enforcement
│   ├── test_agent_constants.py               # Agent name & InMemoryStore keys
│   ├── test_data_fetch_guardrails.py
│   ├── test_cognitive_*.py
│   ├── test_param_evolution.py
│   ├── test_param_overrides.py
│   └── ...
├── api/                               # API endpoint tests
│   ├── conftest.py
│   ├── test_health_memory_mode.py
│   ├── test_learning_routes.py
│   ├── test_decisions_routes.py
│   ├── test_notifications_routes.py
│   ├── test_websocket_fixes.py
│   ├── test_dlq_api.py
│   ├── test_llm_health_redis_metrics.py
│   ├── test_tool_registry.py
│   ├── test_prompt_evolution_endpoint.py
│   ├── test_redis_store.py
│   └── ...
├── agents/                            # Per-agent tests (local only — not in CI)
│   ├── test_signal_generator*.py (3)
│   ├── test_reasoning_agent.py
│   ├── test_execution_engine*.py (3)
│   ├── test_grade_agent.py
│   ├── test_ic_updater.py
│   ├── test_reflection_agent.py
│   ├── test_strategy_proposer.py
│   ├── test_notification_agent.py
│   ├── test_proposal_applier.py
│   ├── test_challenger_agent.py
│   ├── test_position_math.py          # 35 pure-function unit tests
│   ├── test_in_memory_persistence.py
│   └── ...
└── integration/                       # End-to-end pipeline tests
```

## Run tests

CI runs two separate commands — always mirror this locally:

```bash
# Unit tests — mirrors CI step (run first)
pytest tests/core tests/api -v --tb=short

# Integration tests — mirrors CI step (run second)
pytest tests/integration -v --tb=short

# Agent tests — local only, not in CI, catch regressions before pushing
pytest tests/agents -v --tb=short

# Single file
pytest tests/core/test_signal_pipeline.py -v

# With coverage report
pytest tests/core tests/api -v --tb=short --cov=api --cov-report=term-missing
```

**Never run `pytest tests/` combined** — the CI pipeline runs two separate subset commands, so ordering-sensitive failures only appear when you run them split.

## Writing tests

### Agent tests

```python
import pytest
from unittest.mock import AsyncMock
from api.events.bus import EventBus

@pytest.fixture
def mock_redis():
    return AsyncMock(spec=EventBus)

async def test_agent_processes_event(mock_redis):
    event = {
        "type": "signal",
        "data": {"symbol": "BTC/USD", "signal_type": "MOMENTUM"},
        "trace_id": "test-trace-123",
    }
    # assert processing result
```

### Database tests

Use `FakeAsyncSession` from `tests/core/fake_session.py` — never connect to a real DB in unit tests.

```python
from tests.core.fake_session import FakeAsyncSession

async def test_safe_writer(fake_session: FakeAsyncSession):
    writer = SafeWriter(fake_session)
    record_id = await writer.write(table="orders", data={...}, schema_version="v3", source="test")
    assert record_id is not None
```

### Memory-mode dashboard tests

Dashboard read paths have a hard rule: when `set_db_available(False)` is active, they must not create a SQLAlchemy session at all.

Use a recording `AsyncSessionFactory` in tests and assert it was never called. A fallback that first tries Postgres and then returns memory data is still a bug, because production DNS failures can block before fallback logic runs.

```python
factory_calls = []

def recording_factory():
    factory_calls.append("called")
    raise AssertionError("DB session should not be created in memory mode")

monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", recording_factory)
set_db_available(False)

payload = await dashboard_v2.get_dashboard_state()

assert payload["source"] == "in_memory" or payload["mode"] == "in_memory_fallback"
assert factory_calls == []
```

Add or update this coverage for every new dashboard, websocket hydration, or metrics read endpoint.

### Redis tests

Use `FakeAsyncRedis` from the `fakeredis` PyPI package — never connect to a real Redis in unit tests. The `fake_redis` fixture in `tests/conftest.py` provides a pre-configured instance.

```python
import pytest_asyncio
import fakeredis

@pytest_asyncio.fixture
async def redis():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield r
    await r.aclose()
```

**Important:** Use positional arguments with `xgroup_create`:

```python
# Correct
await redis.xgroup_create(stream, group, "$", mkstream=True)

# Wrong — keyword arg breaks compatibility
await redis.xgroup_create(stream, group, id="$", mkstream=True)
```

## CI requirements

All tests must pass before any merge. CI runs Python 3.10 and 3.11 in parallel:

```bash
# Step 1 — Lint (ruff)
ruff check . --fix
ruff format --check .
ruff check . --select=E9,F63,F7,F82

# Step 2 — Unit tests
pytest tests/core tests/api -v

# Step 3 — Integration tests
pytest tests/integration -v
```

`tests/agents/` is **not** in CI — run it locally before pushing to catch agent regressions. Zero failures required across all steps. No exceptions.

## Contributor expectations

- Add or update tests whenever behavior changes.
- Every new agent gets a test in `tests/agents/test_{agent_name}.py`.
- Every new endpoint gets a test in `tests/api/test_{router_name}.py`.
- Tests must be deterministic — no network calls, no real DB/Redis.
- Keep tests small and focused — one behavior per test.
