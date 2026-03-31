# Testing Guide

## Test structure

```
tests/
├── core/                        # Core unit tests
│   ├── conftest.py
│   ├── fake_session.py          # FakeAsyncSession for DB mocking
│   ├── async_sqlalchemy_mocks.py
│   ├── test_api_modularization.py
│   ├── test_basic.py
│   ├── test_database_bootstrap.py
│   ├── test_event_stack.py
│   ├── test_logging_safety.py
│   ├── test_mocks.py
│   ├── test_redis_init.py
│   ├── test_runtime_hardening.py
│   ├── test_schema_mapping.py
│   ├── test_signal_pipeline.py
│   └── test_structlog_safety.py
├── api/                         # API endpoint tests
│   ├── conftest.py
│   ├── test_dlq_api.py
│   └── test_websocket_fixes.py
├── integration/                 # Integration tests
├── test_embedding_validation.py
├── test_no_unknown_ids.py
└── test_stream_logic.py
```

## Run tests

```bash
# Full suite (required before any merge)
pytest tests/ -v --tb=short

# With coverage report
pytest tests/ -v --tb=short --cov=api --cov-report=term-missing

# Specific categories
pytest tests/core/ -v      # Core unit tests
pytest tests/api/ -v       # API endpoint tests
pytest tests/integration/  # Integration tests

# Single file
pytest tests/core/test_signal_pipeline.py -v
```

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

All tests must pass before any merge. The CI runs:

```bash
pytest tests/core tests/api -v      # Unit tests
pytest tests/integration -v         # Integration tests
```

Zero failures required. No exceptions.

## Contributor expectations

- Add or update tests whenever behavior changes.
- Every new agent gets a test in `tests/agents/test_{agent_name}.py`.
- Every new endpoint gets a test in `tests/api/test_{router_name}.py`.
- Tests must be deterministic — no network calls, no real DB/Redis.
- Keep tests small and focused — one behavior per test.
