# CI/CD Patterns & Common Fixes

## Critical CI/CD Commands (Must Pass)

### Exact Pipeline Commands
```bash
# Step 1: Ruff linting (must show "All checks passed!")
ruff check . --fix

# Step 2: Ruff formatting (must show "X files already formatted") 
ruff format --check .

# Step 3: Critical error checks (must show "All checks passed!")
ruff check . --select=E9,F63,F7,F82

# Step 4: Test suite (all tests must pass)
pytest tests/ -v --tb=short
```

### Pre-push Verification
```bash
# Run complete CI/CD check locally
ruff check . --fix && \
ruff format --check . && \
ruff check . --select=E9,F63,F7,F82 && \
pytest tests/ -v --tb=short
```

## Common CI/CD Failure Patterns & Fixes

### B008: Function Call in Default Argument
```python
# ❌ WRONG - B008 error
async def analyze_trade(request, trading_service=Depends(get_trading_service)):

# ✅ RIGHT - Use Annotated syntax
from typing import Annotated
async def analyze_trade(
    request, 
    trading_service: Annotated[TradingService, Depends(get_trading_service)]
):
```

### F821: Undefined Name (Missing Import)
```python
# ❌ WRONG - F821 error
trading_service: Annotated[TradingService, Depends(get_trading_service)]

# ✅ RIGHT - Add missing import
from api.services.trading_service import TradingService
trading_service: Annotated[TradingService, Depends(get_trading_service)]
```

### B904: Raise Without From
```python
# ❌ WRONG - B904 error
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

# ✅ RIGHT - Add exception chaining
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e)) from None
```

### Redis Compatibility Issues
```python
# ❌ WRONG - Test failures with FakeRedis
await redis.xgroup_create(stream, group, id="$", mkstream=True)

# ✅ RIGHT - Use positional arguments
await redis.xgroup_create(stream, group, "$", mkstream=True)
```

### Logging Pattern Violations
```python
# ❌ WRONG - CI/CD failure
log_structured("error", "operation failed", error=str(exc))

# ✅ RIGHT - Use exc_info=True
log_structured("error", "operation failed", exc_info=True)
```

## Code Quality Checks

### Print Statement Detection
```bash
# Must return empty (no print statements)
grep -rn "^[[:space:]]*print(" api/ --include="*.py" | grep -v ".pyc"
```

### Logger Call Detection
```bash
# Must return empty (no old logger calls)
grep -rn "logger\." api/ --include="*.py" | grep -v "logger = logging.getLogger"
```

### Hardcoded URL Detection
```bash
# Must return empty (no hardcoded URLs)
grep -rn "onrender\.com\|vercel\.app\|localhost:8000" \
    frontend/src/ --include="*.ts" --include="*.tsx" \
    | grep -v ".env" | grep -v "CLAUDE.md"
```

## Schema Version Compliance

### Database Write Requirements
```python
# All new writes must include schema_version
await writer.write(
    table="agent_runs",
    data={
        "strategy_id": strategy_id,
        "symbol": "BTC/USD",
        "action": "buy",
        "schema_version": "v3",  # MANDATORY
        "source": "reasoning_agent"
    }
)
```

### Schema Version Validation
```bash
# Check all agent_runs have schema_version='v3'
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs WHERE schema_version='v3';"

# Should equal total count
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs;"
```

## Test Requirements

### Test File Naming
```bash
# Test files must follow pattern
tests/test_{module_name}.py
tests/agents/test_{agent_name}.py
tests/api/test_{router_name}.py
```

### Test Coverage Requirements
- Every agent: `tests/agents/test_{agent_name}.py`
- Every API router: `tests/api/test_{router_name}.py`
- Bug fixes: Add regression test that would have caught the bug

### Common Test Patterns
```python
# Agent testing with trace ID
@pytest.mark.asyncio
async def test_reasoning_agent_trace_propagation():
    event_data = {
        "type": "signal",
        "data": {"symbol": "BTC/USD"},
        "trace_id": "test-trace-123"
    }
    
    result = await reasoning_agent.process_event(event_data)
    assert result["trace_id"] != "test-trace-123"  # New trace generated
    assert "incoming_trace_id" in result  # Original preserved

# Database testing with FakeAsyncSession
async def test_safe_writer_idempotency():
    session = FakeAsyncSession()
    writer = SafeWriter(session)
    
    # First write
    record_id_1 = await writer.write(table="orders", data=data, 
                                   idempotency_key="test-key",
                                   schema_version="v3")
    
    # Second write (should return same ID)
    record_id_2 = await writer.write(table="orders", data=data,
                                   idempotency_key="test-key", 
                                   schema_version="v3")
    
    assert record_id_1 == record_id_2
```

## Performance Standards

### Linting Performance
- Target: <10 seconds for `ruff check . --fix`
- Target: <5 seconds for `ruff format --check .`

### Test Performance  
- Target: <30 seconds for full test suite
- Target: <5 seconds for individual test files

### Memory Usage
- CLAUDE.md: <200 lines (core memory)
- Rule files: <500 lines each (focused)
- Total context: <40k characters per file
