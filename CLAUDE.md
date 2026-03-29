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

## API & Documentation (Fern)

**Live Docs**: https://matthew.docs.buildwithfern.com/
**Private Repo**: https://github.com/fern-support/matthew

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

**Never merge a PR that adds or changes an endpoint without a matching Fern definition update.**
