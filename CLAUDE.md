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

## Task Management

For any task that involves more than 2 files or 3 steps:

1. Write the plan to `.claude/tasks/todo.md` before writing any code
2. Show me the plan and wait for confirmation
3. Mark items complete as you go: [x] done, [ ] pending
4. Give a one-line summary after each major step
5. Add a ## Results section when done
6. Update `.claude/tasks/lessons.md` if anything went wrong

Never start implementation without a written plan for complex tasks.

---

## Lessons Learned

When you make a mistake and get corrected, immediately add a rule 
to `.claude/tasks/lessons.md` in this format:

## [date] — [Component Name] failure
- Mistake: [e.g., Agent generated a new UUID instead of propagating trace_id]
- Fix: [e.g., Always pull trace_id from the Redis stream header]
- Rule: **NEVER** use `uuid4()` inside an agent's `process_event` loop.

**Anti-Pattern vs Pattern Documentation:**
- **Anti-Pattern**: What NOT to do (the mistake)
- **Pattern**: What TO do instead (the correct approach)

Then update CLAUDE.md if the lesson applies globally.

---

## Definition of Done

Before marking ANY task complete, every item below must be true.
Do not say "done" until you have verified each section.
Show me the output of every verification command.

===================================================================
1. TESTS
===================================================================

Run the full test suite:
  pytest tests/ -v --tb=short 2>&1 | tee .claude/tasks/last_test_run.txt

Rules:
  - Zero failing tests. No exceptions.
  - If you fixed a bug, you added a test that would have caught it.
  - Test file naming: tests/test_{module_name}.py
  - Every agent must have a test in tests/agents/test_{agent_name}.py
  - Every endpoint must have a test in tests/api/test_{router_name}.py

===================================================================
2. LINTING & CI/CD COMPLIANCE
===================================================================

**CRITICAL: CI/CD Pipeline Requirements**
The CI/CD pipeline runs these exact commands and ALL must pass:

```bash
# Step 1: Ruff linting (must show "All checks passed!")
ruff check . --fix

# Step 2: Ruff formatting (must show "X files already formatted") 
ruff format --check .

# Step 3: Critical error checks (must show "All checks passed!")
ruff check . --select=E9,F63,F7,F82
```

**Local Development Commands:**
```bash
# Fix all linting issues
ruff check . --fix

# Format all files (use ruff format, NOT black)
ruff format .

# Verify everything is CI-ready
ruff check . --fix && ruff format --check . && ruff check . --select=E9,F63,F7,F82
```

**CI/CD Failure Patterns to Avoid:**
- **A002**: Function argument shadowing Python builtin (rename `id` → `id_param`)
- **B008**: Function call in default argument (use `Annotated[Type, Depends(...)]`)
- **B904**: Raise without from inside except (add `from None` or `from err`)
- **E722**: Bare except (specify exception types)
- **F821**: Undefined name (add missing imports)
- **UP006/UP035**: Deprecated typing (use `dict` not `Dict`)
- **N806**: Variable in function should be lowercase
- **I001**: Unsorted imports (run `ruff format .` to fix)

**Redis/FakeRedis Compatibility:**
- `redis.xgroup_create(stream, group, "$", mkstream=True)` ✅
- `redis.xgroup_create(stream, group, id="$", mkstream=True)` ❌ (use positional, not keyword)

**Logging Standards (CI/CD enforced):**
- Use `exc_info=True` NOT `error=str(exc)` in log_structured calls
- All error logging must include proper exception info

**Frontend — ESLint + Prettier (if frontend changes):**
cd frontend && npm run lint:fix && npm run format

**Print Statement Check:**
  grep -rn "^[[:space:]]*print(" api/ --include="*.py" | grep -v ".pyc"
Expected: empty

===================================================================
3. LOGGING
===================================================================

**Standard Logging Function**: Always use `log_structured()` from `api.observability`
```python
from api.observability import log_structured

# For errors (CI/CD requirement):
log_structured("error", "operation failed", exc_info=True, context=data)

# For general logging:
log_structured("info", "operation completed", key=value, other=data)
```

Rules:
- No logger.info/error/warning calls in new code
- No print statements anywhere
- All error logs MUST use `exc_info=True` (CI/CD enforced)
- All logs must use structured key=value format
- trace_id propagated: Any new agent code extracts trace_id from incoming event payload

===================================================================
4. CODE QUALITY
===================================================================

No hardcoded values:
  grep -rn "onrender\.com\|vercel\.app\|localhost:8000" \
      frontend/src/ --include="*.ts" --include="*.tsx" \
      | grep -v ".env" | grep -v "CLAUDE.md"

Expected: empty

Schema version on every insert:
  Any new INSERT to a versioned table includes schema_version='v2'
  and source='<service_name>'. Manually verify any new INSERT statements.

===================================================================
5. CI/CD PIPELINE VERIFICATION
===================================================================

**Before pushing ANY changes, verify CI/CD will pass:**

```bash
# Run the EXACT CI/CD commands locally
ruff check . --fix
echo "Exit code: $?"  # Must be 0

ruff format --check .
echo "Exit code: $?"  # Must be 0

ruff check . --select=E9,F63,F7,F82
echo "Exit code: $?"  # Must be 0
```

**Expected Outputs:**
- `ruff check . --fix` → "All checks passed!"
- `ruff format --check .` → "X files already formatted" (no "Would reformat")
- `ruff check . --select=E9,F63,F7,F82` → "All checks passed!"

**If any command fails, DO NOT PUSH. Fix issues first.**

**Common CI/CD Blockers:**
- New imports not added (F821)
- Exception handling missing `from None` (B904)  
- FastAPI dependencies using old pattern (B008)
- Redis calls using keyword arguments (test failures)
- Logging using `error=str(exc)` instead of `exc_info=True`

===================================================================
6. SYSTEM VERIFICATION
===================================================================

### Redis Streams Verification
```bash
redis-cli xlen signals                       # > 0 within 30s of poller starting
redis-cli xlen decisions                     # > 0 shortly after
redis-cli xlen graded_decisions              # > 0 shortly after
redis-cli keys "agent:status:*"              # should show all 7 agents
```

### Database Verification
```bash
# Check database health
psql $DATABASE_URL -c "SELECT agent_name, status, event_count, last_seen FROM agent_heartbeats;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs WHERE status='completed';"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM processed_events;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_pool;"  # should be 7
```

### CI/CD Testing
The pipeline will automatically run:
- **Backend**: ruff check/format, mypy, pytest (unit + integration)
- **Frontend**: ESLint, TypeScript check, build, tests with coverage

If any step fails, the PR cannot be merged.

===================================================================
6. FINAL CHECKLIST — RUN THIS BEFORE SAYING DONE
===================================================================

Copy this block, run every command, paste the results:
  echo "=== TESTS ===" && pytest tests/ -v --tb=short | tail -5
  echo "=== RUFF ===" && ruff check api/ tests/ && echo "PASS"
  echo "=== PRINT STATEMENTS ===" && grep -rn "print(" api/ --include="*.py" | wc -l
  echo "=== LOGGER CALLS ===" && grep -rn "logger\." api/ --include="*.py" | grep -v "logger = logging.getLogger" | wc -l

---

## API & Documentation (Fern)

**Live Docs**: https://matthew.docs.buildwithfern.com/
**Private Repo**: https://github.com/fern-support/matthew
**Repository**: fern-support/matthew (accessible via GitHub MCP tool)

### Sync Requirements
**ANY change to api/ endpoints requires an update to the Fern definition** in the private fern-support/matthew repo.

### Sync Flow
1. **Code Change**: Modify endpoint in this repo
2. **Update Fern YAML**: Edit the Fern definition in fern-support/matthew repo  
3. **Commit Both**: Commit code change here AND docs change in Fern repo
4. **Update CHANGELOG.md**: Document both changes in this repo's CHANGELOG.md

### Before Making Endpoint Changes
Use the GitHub MCP tool to read the current Fern definition files from fern-support/matthew to understand the current documented state.

### After Making Endpoint Changes
1. Use the GitHub MCP tool to update the Fern definition in fern-support/matthew to match
2. Commit both changes - code change here, docs change in Fern repo
3. Update CHANGELOG.md with both changes

### Fern Repo Access
- **Repository Name**: fern-support/matthew
- **Full URL**: https://github.com/fern-support/matthew
- **Access Method**: GitHub MCP tool (available in this environment)
- **Purpose**: Private repository for Fern API definitions
- **Contents**: YAML files defining API endpoints, types, and documentation

### Definition Files Location
The Fern definition files are typically located in:
- `fern/definition/` directory
- `fern/api.yml` or similar YAML files
- `fern/docs/` for additional documentation

**Never merge a PR that adds or changes an endpoint without a matching Fern definition update.**
