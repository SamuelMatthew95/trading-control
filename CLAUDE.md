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
  - No skipped tests unless they were already skipped before your change.
  - If you broke a test, fix the root cause — do not mock around it
    or add pytest.mark.skip to hide it.
  - If you added a new feature, you added a new test for it.
  - If you fixed a bug, you added a test that would have caught it.
  - Test file naming: tests/test_{module_name}.py
  - Every agent must have a test in tests/agents/test_{agent_name}.py
  - Every endpoint must have a test in tests/api/test_{router_name}.py

===================================================================
2. LINTING
===================================================================

Run all linters and fix every warning before marking done:

  # Python — Ruff (fast linter + formatter)
  ruff check api/ tests/ --fix
  ruff format api/ tests/

  # Python — type checking
  mypy api/ --ignore-missing-imports --no-error-summary

  # TypeScript — compiler check
  cd frontend && npx tsc --noEmit

  # TypeScript — ESLint
  cd frontend && npx eslint src/ --ext .ts,.tsx --max-warnings 0

Rules:
  - Zero ruff errors after --fix. If --fix cannot resolve it, fix it manually.
  - Zero TypeScript compiler errors.
  - Zero ESLint errors. Warnings allowed only if pre-existing.
  - No unused imports anywhere.
  - No unused variables anywhere.
  - Line length max 100 characters (configured in ruff).
  - No bare except: clauses — always except SpecificError as e:
  - No print() statements in Python — use logger only.
  - No console.log() left in TypeScript — use structured logging only.

Run this to catch print statements:
  grep -rn "^[[:space:]]*print(" api/ --include="*.py" | grep -v ".pyc"
  Expected: empty

===================================================================
3. LOGGING
===================================================================

**Standard Logging Function**: Always use `log_structured()` from `api.observability`

```python
from api.observability import log_structured

# Correct usage
log_structured("info", "price fetched", symbol="BTC/USD", price=65234.50)
log_structured("warning", "duplicate skipped", msg_id="1234-0", stream="market_events")
log_structured("error", "agent_runs write failed", run_id="abc", error="UniqueViolation")
```

Every log line in the entire codebase must follow this format:
  [service_name] action: key=value key=value — outcome

Verify log format compliance:
  grep -rn "log_structured\|logger\." api/ --include="*.py" | head -30
  Each line should have [service_name] prefix and key=value pairs.

Rules:
  - Every log line starts with [service_name] in brackets
  - Use key=value pairs for all machine-readable data
  - Always include trace_id when processing an agent event
  - Always include symbol when processing price or signal data
  - Always include msg_id when reading from a Redis stream
  - Always include the outcome after a dash at the end
  - Use the correct level with log_structured:
      log_structured("info", ...)    → normal operations, expected flow
      log_structured("warning", ...) → degraded but continuing (timeout, skip, retry)
      log_structured("error", ...)   → failure requiring attention, not crashing
      log_structured("critical", ...)→ process must exit

  Good examples:
    log_structured("info", "BTC/USD fetched", price=65234.50, change=120.30, pct=0.18, ts=1234567890)
    log_structured("info", "cycle complete", symbols=6, duration_ms=340)
    log_structured("warning", "duplicate skipped", msg_id="1234-0", stream="market_events")
    log_structured("error", "agent_runs write failed", run_id="abc", error="UniqueViolation", outcome="event still processed")
    log_structured("info", "decision", action="BUY", symbol="BTC/USD", confidence=0.75, trace_id="abc-123")

  Bad examples (fix these):
    logger.info("Processing event")                    # no service name, no data
    logger.error(f"Error: {e}")                        # no context, no outcome
    logger.info(f"Done")                               # meaningless
    print(f"BTC price: {price}")                       # print not allowed
    log_structured("warning", "Something went wrong")  # not actionable

trace_id propagated:
  Any new agent code extracts trace_id from incoming event payload.
  Confirm it is NOT generating a new uuid4() mid-chain.

===================================================================
4. CODE QUALITY
===================================================================

No hardcoded values:
  grep -rn "onrender\.com\|vercel\.app\|localhost:8000" \
    frontend/src/ --include="*.ts" --include="*.tsx" \
    | grep -v ".env" | grep -v "CLAUDE.md"
  Expected: empty

No hardcoded credentials:
  grep -rn "ghp_\|sk-\|pk-lf\|AKIA" . \
    --include="*.py" --include="*.ts" --include="*.json" \
    | grep -v ".env" | grep -v ".gitignore"
  Expected: empty

Schema version on every insert:
  Any new INSERT to a versioned table includes schema_version='v2'
  and source='<service_name>'. Manually verify any new INSERT statements.

===================================================================
5. FINAL CHECKLIST — RUN THIS BEFORE SAYING DONE
===================================================================

Copy this block, run every command, paste the results:

  echo "=== TESTS ===" && pytest tests/ -v --tb=short | tail -5
  echo "=== RUFF ===" && ruff check api/ tests/ && echo "PASS"
  echo "=== MYPY ===" && mypy api/ --ignore-missing-imports --no-error-summary | tail -3
  echo "=== TSC ===" && cd frontend && npx tsc --noEmit && echo "PASS" && cd ..
  echo "=== PRINT STATEMENTS ===" && grep -rn "^[[:space:]]*print(" api/ --include="*.py" | wc -l
  echo "=== SLEEPS ===" && grep -rn "asyncio\.sleep" api/ --include="*.py" | grep -v "sleep(5)" | wc -l
  echo "=== HARDCODED URLS ===" && grep -rn "onrender\.com\|localhost:8000" frontend/src/ --include="*.ts" --include="*.tsx" | wc -l
  echo "=== ENV STAGED ===" && git status | grep "^[AM].*\.env$" | wc -l

  Expected output:
    TESTS:           X passed, 0 failed
    RUFF:            PASS
    MYPY:            PASS or known pre-existing errors only
    TSC:             PASS
    PRINT STATEMENTS: 0
    SLEEPS:          0
    HARDCODED URLS:  0
    ENV STAGED:      0

If any number is wrong, fix it before saying done.
Only when all lines show the expected value is the task complete.

---

## Testing the Whole Application

### Before Making Changes
Always run this to verify current state:
```bash
# 1. Check git status
git status

# 2. Run full test suite
pytest tests/ -v --tb=short

# 3. Check linting
ruff check api/ tests/ --fix
ruff format api/ tests/

# 4. Type checking
mypy api/ --ignore-missing-imports --no-error-summary

# 5. Frontend checks
cd frontend && npx tsc --noEmit && npx eslint src/ --ext .ts,.tsx --max-warnings 0 && cd ..
```

### After Making Changes
Run this complete verification checklist:
```bash
echo "=== TESTS ===" && pytest tests/ -v --tb=short | tail -5
echo "=== RUFF ===" && ruff check api/ tests/ && echo "PASS"
echo "=== MYPY ===" && mypy api/ --ignore-missing-imports --no-error-summary | tail -3
echo "=== TSC ===" && cd frontend && npx tsc --noEmit && echo "PASS" && cd ..
echo "=== PRINT STATEMENTS ===" && grep -rn "^[[:space:]]*print(" api/ --include="*.py" | wc -l
echo "=== SLEEPS ===" && grep -rn "asyncio\.sleep" api/ --include="*.py" | grep -v "sleep(5)" | wc -l
echo "=== HARDCODED URLS ===" && grep -rn "onrender\.com\|localhost:8000" frontend/src/ --include="*.ts" --include="*.tsx" | wc -l
echo "=== ENV STAGED ===" && git status | grep "^[AM].*\.env$" | wc -l
```

Expected output:
- TESTS: X passed, 0 failed
- RUFF: PASS
- MYPY: PASS or known pre-existing errors only
- TSC: PASS
- PRINT STATEMENTS: 0
- SLEEPS: 0
- HARDCODED URLS: 0
- ENV STAGED: 0

### Linting Philosophy
This project uses ruff as the primary linter with a pragmatic approach:

**Critical Errors (FAIL)**: Syntax errors, undefined variables, import issues
- These block commits and must be fixed immediately
- Checked in CI/CD with `ruff check --select=E9,F63,F7,F82`

**Style & Code Quality (WARN)**: Formatting, unused imports, naming conventions
- These are warnings, not blockers
- Auto-fixed with `ruff check --fix` and `ruff format`
- Reviewed during PR but won't block deployment

**Allowed Sleeps**: Not all sleeps are defensive - these are explicitly allowed:
- `await asyncio.sleep(5)` - Price poller interval (core business logic)
- Rate limit backoffs - API retry logic
- Error recovery delays - Fault tolerance
- WebSocket idle sleeps - Resource management
- Agent processing throttles - Performance control

### Running the Application Locally
```bash
# Backend (Terminal 1)
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Price poller (Terminal 2) 
source .venv/bin/activate
python -m api.workers.price_poller

# Frontend (Terminal 3)
cd frontend
npm run dev

# Verify everything is working
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/prices | python3 -m json.tool
curl -N --max-time 10 http://localhost:8000/api/v1/prices/stream
```

### Redis Verification
```bash
# Check price poller is writing
redis-cli keys "prices:*"                    # should show 6 keys
redis-cli xlen market_events                 # should be > 0 and growing

# Check agents are firing
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

---

## API Documentation (Fern)

Live docs: https://matthew.docs.buildwithfern.com/
Fern source: private GitHub repo — accessible via GitHub MCP tool.

### Reading the docs
When you need to understand current API structure, use the GitHub MCP
tool to read the Fern definition files from the private repo before
making any endpoint changes.

### Keeping docs in sync
When you add or change any API endpoint, you must:
1. Make the code change in this repo
2. Use the GitHub MCP tool to read the current Fern definition
3. Update the Fern definition file in the private repo to match
4. Commit both changes — code change here, docs change in Fern repo
5. Note both changes in CHANGELOG.md

Never merge a PR that adds or changes an endpoint without a matching
Fern definition update.

### Fern repo details
- Repo name: fern-support/matthew
- Repo URL: https://github.com/fern-support/matthew/
- Definition files location: [add path once confirmed e.g. fern/definition/]
- To verify changes published: check https://matthew.docs.buildwithfern.com/
