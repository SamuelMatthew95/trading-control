# Trading Control — Core Memory (The "Permanent Seed")

**Project**: Event-driven algorithmic trading platform with 7 specialized agents
**Version**: Schema v3, Python 3.10+, FastAPI + Next.js architecture

## Tech Stack (High-Level)
- **Backend**: FastAPI (Python 3.10+) on Render
- **Frontend**: Next.js 14 (TypeScript) on Vercel  
- **Database**: PostgreSQL 15+ with pgvector extension
- **Cache/Streams**: Redis 5.0+ for agent communication
- **Market Data**: Alpaca API (paper trading mode)

## Core Architecture Principles
1. **Event-Driven**: Agents communicate via Redis Streams only
2. **Traceability**: Every operation carries `trace_id` through entire system
3. **Idempotency**: Orders and events use idempotency keys
4. **Schema Version**: All new writes must use `schema_version='v3'`

## 7-Agent System (Phase 1 Complete)
- **SignalGenerator**: market_ticks → signals
- **ReasoningAgent**: signals → decisions (LLM-powered)
- **ExecutionEngine**: orders → executions  
- **GradeAgent**: executions → performance scores
- **ICUpdater**: performance → factor weights
- **ReflectionAgent**: performance → hypotheses
- **StrategyProposer**: hypotheses → proposals

## Critical Anti-Patterns (NEVER Do These)
- ❌ `log_structured("error", "msg", error=str(exc))` → Use `exc_info=True`
- ❌ `redis.xgroup_create(stream, group, id="$", mkstream=True)` → Use positional args
- ❌ `async def endpoint(service=Depends(get_service))` → Use `Annotated[Service, Depends(...)]`
- ❌ `raise HTTPException(str(e))` → Add `from None`
- ❌ Missing imports for types → Always import what you use

## CI/CD Commands (Must Pass)
```bash
ruff check . --fix                    # Linting
ruff format --check .                 # Formatting  
ruff check . --select=E9,F63,F7,F82   # Critical errors
pytest tests/ -v --tb=short          # All tests pass
```

## Additional Rules (Always Loaded)
@./.claude/rules/memory-trading.md     # Alpaca trading specifics
@./.claude/rules/memory-agents.md      # Agent hand-off protocols  
@./.claude/rules/memory-logging.md     # Trace ID & logging standards
@./.claude/rules/memory-cicd.md       # CI/CD patterns and fixes
