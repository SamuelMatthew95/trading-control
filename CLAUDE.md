# CLAUDE.md — Trading Control

This file is read by Claude Code at the start of every session.
Follow every rule here without exception. Do not skip sections.
Do not ask permission to follow these rules — just follow them.

---

## Project Overview

Trading Control is an event-driven algorithmic trading platform.

- **Backend**: FastAPI (Python 3.10+) on Render
- **Frontend**: Next.js 14 (TypeScript) on Vercel  
- **Database**: PostgreSQL 15+ with pgvector extension on Render
- **Cache/Streams**: Redis 5.0+ on Render
- **Market Data**: Alpaca API (paper trading mode)
- **Repo**: https://github.com/SamuelMatthew95/trading-control
- **Live App**: https://trading-control-khaki.vercel.app/dashboard
- **Schema Version**: v3 (upgraded from v2)
- **Python Version**: 3.10+ (target-version in ruff.toml)
- **Linting**: Ruff (line-length 100, target-version "py310")

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

# For errors (CI/CD REQUIREMENT - MUST use exc_info=True):
try:
    dangerous_operation()
except Exception as exc:
    log_structured("error", "operation failed", exc_info=True, context=data)

# For general logging:
log_structured("info", "operation completed", key=value, other=data)

# For warnings with context:
log_structured("warning", "retry attempt", attempt=3, max_attempts=5)
```

**CRITICAL LOGGING RULES (CI/CD Enforced):**
- ❌ **WRONG**: `log_structured("error", "failed", error=str(exc))`
- ✅ **RIGHT**: `log_structured("error", "failed", exc_info=True)`
- ❌ **WRONG**: `logger.error("message")` (old logging)
- ✅ **RIGHT**: `log_structured("error", "message", exc_info=True)`
- ❌ **WRONG**: `print("debug info")` (never use print)
- ✅ **RIGHT**: `log_structured("info", "debug info", data=value)

**Why exc_info=True is Required:**
- Provides full exception traceback for debugging
- CI/CD tests specifically check for this pattern
- Enables proper error monitoring and alerting
- Maintains structured logging consistency

**Common Logging Mistakes We Fixed:**
1. **api/core/db/session.py:94** - Changed `error=str(exc)` → `exc_info=True`
2. **api/core/db/session.py:105** - Changed `error=str(exc)` → `exc_info=True`  
3. **api/services/multi_agent_orchestrator.py:169** - Changed `error=str(exc)` → `exc_info=True`

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
- **New imports not added (F821)**: Always add imports for new types
  ```python
  # ❌ WRONG - F821 error
  trading_service: Annotated[TradingService, Depends(get_trading_service)]
  
  # ✅ RIGHT - import added
  from api.services.trading_service import TradingService
  trading_service: Annotated[TradingService, Depends(get_trading_service)]
  ```

- **Exception handling missing `from None` (B904)**: Always chain exceptions properly
  ```python
  # ❌ WRONG - B904 error
  except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))
  
  # ✅ RIGHT - proper exception chaining
  except Exception as e:
      raise HTTPException(status_code=500, detail=str(e)) from None
  ```

- **FastAPI dependencies using old pattern (B008)**: Use Annotated syntax
  ```python
  # ❌ WRONG - B008 error
  async def endpoint(service=Depends(get_service)):
  
  # ✅ RIGHT - Annotated syntax
  async def endpoint(service: Annotated[ServiceType, Depends(get_service)]):
  ```

- **Redis calls using keyword arguments (test failures)**: Use positional args
  ```python
  # ❌ WRONG - test failures
  await redis.xgroup_create(stream, group, id="$", mkstream=True)
  
  # ✅ RIGHT - positional arguments
  await redis.xgroup_create(stream, group, "$", mkstream=True)
  ```

- **Logging using `error=str(exc)` instead of `exc_info=True`**: CI/CD enforced
  ```python
  # ❌ WRONG - CI/CD failure
  log_structured("error", "failed", error=str(exc))
  
  # ✅ RIGHT - CI/CD compliant
  log_structured("error", "failed", exc_info=True)
  ```

**Recent Fixes Applied (Learning Examples):**
1. **Redis xgroup_create calls** - Fixed 5 test failures by removing `id=` keyword
2. **Logging patterns** - Fixed 3 CI/CD failures by using `exc_info=True`
3. **Exception chaining** - Fixed 29 B904 errors by adding `from None`
4. **FastAPI dependencies** - Fixed 12 B008 errors with `Annotated` syntax
5. **Import issues** - Fixed 9 F821 errors by adding missing imports

===================================================================
7. COMMON MISTAKES & HOW WE FIXED THEM
===================================================================

This section documents the exact mistakes we encountered and their fixes.
Use this as a reference to avoid repeating these issues.

## Redis/FakeRedis Compatibility Issues

**Mistake**: Using keyword arguments with `xgroup_create`
```python
# ❌ WHAT WE DID WRONG (5 test failures)
await redis.xgroup_create(stream, DEFAULT_GROUP, id="$", mkstream=True)
await redis.xgroup_create(stream, group, id="0", mkstream=True)
```

**Fix**: Use positional arguments
```python
# ✅ HOW WE FIXED IT
await redis.xgroup_create(stream, DEFAULT_GROUP, "$", mkstream=True)
await redis.xgroup_create(stream, group, "0", mkstream=True)
```

**Files Fixed**: `api/events/bus.py` (lines 255, 264)

## Logging Pattern Violations

**Mistake**: Using `error=str(exc)` instead of `exc_info=True`
```python
# ❌ WHAT WE DID WRONG (3 CI/CD failures)
log_structured("error", "database readiness error", error=str(exc))
log_structured("warning", "vector table analyze failed", error=str(exc))
log_structured("warning", "reasoning model retry", error=str(exc))
```

**Fix**: Use `exc_info=True` for all error logging
```python
# ✅ HOW WE FIXED IT
log_structured("error", "database readiness error", exc_info=True)
log_structured("warning", "vector table analyze failed", exc_info=True)
log_structured("warning", "reasoning model retry", exc_info=True)
```

**Files Fixed**: 
- `api/core/db/session.py` (lines 94, 105)
- `api/services/multi_agent_orchestrator.py` (line 169)

## Exception Handling Anti-Patterns

**Mistake**: Not chaining exceptions in except blocks
```python
# ❌ WHAT WE DID WRONG (29 B904 errors)
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

**Fix**: Always use `from None` or `from err` for exception chaining
```python
# ✅ HOW WE FIXED IT
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e)) from None
```

**Files Fixed**: Multiple route files and service files

## FastAPI Dependency Injection

**Mistake**: Using old `Depends()` in function defaults
```python
# ❌ WHAT WE DID WRONG (12 B008 errors)
async def analyze_trade(request, trading_service=Depends(get_trading_service)):
async def get_insights(limit=50, feedback_service=Depends(get_feedback_service)):
```

**Fix**: Use `Annotated` syntax
```python
# ✅ HOW WE FIXED IT
async def analyze_trade(request, trading_service: Annotated[TradingService, Depends(get_trading_service)]):
async def get_insights(feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)], limit=50):
```

**Files Fixed**: `api/routes/analyze.py`, `api/routes/feedback.py`, `api/routes/performance.py`, `api/routes/trades.py`

## Missing Import Statements

**Mistake**: Using types without importing them
```python
# ❌ WHAT WE DID WRONG (9 F821 errors)
trading_service: Annotated[TradingService, Depends(get_trading_service)]  # TradingService not imported
feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)]  # FeedbackService not imported
```

**Fix**: Always add the missing imports
```python
# ✅ HOW WE FIXED IT
from api.services.trading_service import TradingService
from api.services.feedback_service import FeedbackService
```

**Files Fixed**: `api/routes/analyze.py`, `api/routes/feedback.py`, `api/routes/performance.py`

## KEY TAKEAWAYS

1. **Always run CI commands locally before pushing**
2. **Use `exc_info=True` for all error logging**
3. **Use positional arguments for Redis calls**
4. **Chain exceptions with `from None`**
5. **Use `Annotated` syntax for FastAPI dependencies**
6. **Add imports for all types you use**

===================================================================
9. SYSTEM ARCHITECTURE
===================================================================

## Agent System Overview

The system is designed for 8 specialized agents that communicate exclusively through Redis Streams. Currently, a subset is implemented with the full architecture in place for expansion.

### Current Implementation Status

**✅ IMPLEMENTED:**

**SignalGenerator** - Generates periodic signals from market ticks
- Listens: `market_ticks` | Publishes: `signals`
- Triggers: Every SIGNAL_EVERY_N_TICKS ticks per symbol (default: 10)
- Located: `api/services/signal_generator.py`

**ReasoningAgent** - Makes trading decisions using LLM reasoning
- Listens: `signals` | Publishes: structured reasoning outputs
- Returns structured JSON only, never raw LLM output
- Features: Token budget tracking, fallback modes, vector memory search
- Located: `api/services/agents/reasoning_agent.py`

**ExecutionEngine** - Executes orders via paper broker, computes realized PnL
- Listens: `orders` | Publishes: `executions`, `trade_performance`
- PnL computed from prior position snapshot (closing trades only)
- Located: `api/services/execution/execution_engine.py`

**Pipeline Agents** - Full learning loop agents, all fully implemented
- **GradeAgent** - Real 4-dimension scoring (accuracy × 0.35 + IC × 0.30 + cost × 0.20 + latency × 0.15), grade letters A+/A/B/C/D/F, automatic actions per threshold, consecutive D-grade tracking
- **ICUpdater** - Spearman rank correlation per factor, zeros factors below IC_ZERO_THRESHOLD, normalizes weights to 1.0, writes `alpha:ic_weights` to Redis + `factor_ic_history` table
- **ReflectionAgent** - LLM call with structured JSON output (winning_factors, losing_factors, hypotheses with confidence, regime_edge, time_of_day_patterns), token budget aware, fallback on LLM failure
- **StrategyProposer** - Filters hypotheses by HYPOTHESIS_MIN_CONFIDENCE, creates typed proposals (parameter_change | code_change | regime_adjustment), signals GitHub PR for rule changes
- **NotificationAgent** - Deduplication via Redis 60s window, severity classification, persists to DB via SafeWriter
- Located: `api/services/agents/pipeline_agents.py`

**AgentStateRegistry** - Tracks all 7 running agents with event counts and last_seen
- All MultiStreamAgent subclasses call `record_event()` on every processed message
- Located: `api/services/agent_state.py`

### Agent Pool Tiers (Future Vision)

**🚧 TODO: IMPLEMENT** - Agent pool management system (Active/Challenger/Retired tiers)

| Tier           | Receives                            | Rules                                                                 |
| -------------- | ----------------------------------- | --------------------------------------------------------------------- |
| **Active**     | Live signals → real orders          | Demoted to Challenger if beaten for CHALLENGER_WIN_DAYS consecutive   |
| **Challenger** | Paper signals only → no real orders | Promoted to Active when it beats Active for CHALLENGER_WIN_DAYS cycles |
| **Retired**    | Nothing — archived forever          | Never deleted. Cannot be reinstated automatically.                    |

**🚧 TODO: IMPLEMENT** - Agent lifecycle management and promotion/demotion logic

### Complete Agent Architecture (Future Vision)

**🚧 TODO: IMPLEMENT** - Full 8-agent system

**✅ SignalGenerator** - Bridges market_ticks → signals stream
**✅ ReasoningAgent** - Makes trading decisions using LLM reasoning  
**🚧 HistoryAgent** - Mines historical data for patterns invisible in single trades
- Reads: `trade_performance` (full history), `vector_memory`, `agent_grades`
- Publishes: `historical_insights`, `proposals`, `notifications`
- Trigger: HISTORY_AGENT_SCHEDULE_CRON (default: Sunday 02:00 UTC)

**✅ GradeAgent** - Scores agents across 4 dimensions after fills
- Listens: `executions`, `trade_performance` | Publishes: `agent_grades`, `proposals`
- Score formula: accuracy×0.35 + ic×0.30 + cost_eff×0.20 + latency×0.15
- Automatic actions based on grade thresholds (A-F)

**✅ ICUpdater** - Reweights alpha factors based on predictive performance
- Listens: `trade_performance` | Publishes: `ic_weights`, `factor_ic_history`
- Computes Spearman correlation, zeros out factors below threshold
- Normalizes remaining weights to sum to 1.0

**✅ ReflectionAgent** - Finds patterns in recent trades, generates hypotheses
- Listens: `trade_performance`, `agent_grades`, `factor_ic_history`
- Publishes: `reflection_outputs`, `notifications`
- Never modifies system directly, only generates analysis

**✅ StrategyProposer** - Turns reflection hypotheses into concrete proposals
- Listens: `reflection_outputs` | Publishes: `proposals`, `notifications`, GitHub PRs
- Every proposal requires explicit approval before application

**✅ NotificationAgent** - Classifies and routes all system events
- Listens: All output streams | Publishes: `notifications` table + WebSocket
- Severity levels: CRITICAL, URGENT, WARNING, INFO
- Deduplication: same event type within 60s merged

### Agent State Registry

Current active agents tracked in `AGENT_NAMES` (7 real running agents):
- SIGNAL_AGENT
- REASONING_AGENT
- GRADE_AGENT
- IC_UPDATER
- REFLECTION_AGENT
- STRATEGY_PROPOSER
- NOTIFICATION_AGENT

Located: `api/services/agent_state.py`
Each agent calls `agent_state.record_event(name)` per processed message → powers live dashboard status.

**🚧 TODO: IMPLEMENT** - Full agent pool registry with Active/Challenger/Retired tier management

### Agent Architecture Patterns

All agents follow these patterns:
1. **Event-Driven**: Communicate via Redis Streams, never direct calls
2. **Traceability**: Every operation carries a `trace_id`
3. **Structured Logging**: Use `log_structured()` with `exc_info=True` for errors
4. **Idempotency**: Handle duplicate events gracefully
5. **Circuit Breaking**: Token budget limits and fallback modes

### Implementation Roadmap

**Phase 1** ✅ **COMPLETE**: Core signal processing
- SignalGenerator ✅
- ReasoningAgent ✅
- ExecutionEngine + PaperBroker ✅ (wired into lifespan, publishes trade_performance)
- GradeAgent with real 4-dimension scoring ✅
- ICUpdater with Spearman correlation ✅
- ReflectionAgent with LLM analysis ✅
- StrategyProposer with typed proposals ✅
- NotificationAgent with deduplication ✅
- AgentStateRegistry with live event counts ✅

**Phase 2** 🚧 **IN PROGRESS**: Agent lifecycle management
- Agent pool tiers (Active/Challenger/Retired)
- Promotion/demotion logic based on grade cycles
- Full agent pool DB registry

**Phase 3** 📋 **PLANNED**: Advanced analytics
- HistoryAgent (scheduled, Sunday 02:00 UTC)
- Historical pattern mining across full trade history
- Automated strategy evolution with human approval gate

## Database Schema Overview

**Current Schema Version: v3** (upgraded from v2)

### Core Tables

**strategies** - Strategy definitions and configuration
- Primary key: UUID | Unique name field
- Contains: rules JSONB, risk_limits JSONB, is_active boolean
- Default strategy: "BTC_MOMENTUM_V3" with momentum-based rules
- Relationships: orders, positions, agent_runs, strategy_metrics

**orders** - All submitted trading orders and lifecycle state
- Idempotency: idempotency_key TEXT NOT NULL UNIQUE prevents duplicate orders
- Fields: strategy_id (FK), symbol, side, qty, price, status, broker_order_id
- Lifecycle: pending → filled/cancelled/rejected
- Relationships: trade_performance, order_reconciliation

**positions** - Current exposure per strategy/symbol pair
- Fields: strategy_id (FK), symbol, side, qty, entry_price, current_price, unrealised_pnl
- No unique constraint on (strategy_id, symbol) in current schema
- Operational meaning: Current position tracking

**trade_performance** - Trade-level outcome data for analysis
- Fields: order_id (FK), symbol, pnl, holding_secs, entry_price, exit_price
- Contains: market_context JSONB, factor_attribution JSONB
- Relationships: Links to orders for performance analysis

### Agent Tables

**agent_runs** - Each execution of an agent
- Fields: strategy_id (FK), symbol, signal_data JSONB, action, confidence
- Contains: primary_edge, risk_factors JSONB, size_pct, stop_atr_x, rr_ratio
- Technical: latency_ms, cost_usd, trace_id, fallback boolean
- Schema: v3 with traceability indexes

**agent_logs** - Structured logs for each agent run
- Fields: trace_id, log_type, payload JSONB
- Schema: v3 with traceability indexes
- Purpose: Step-level execution tracking

**vector_memory** - Embeddings and semantic memory
- pgvector extension: VECTOR(1536) for embeddings
- Fields: content TEXT, embedding VECTOR(1536), metadata_ JSONB, outcome JSONB
- Indexing: ivfflat with vector_cosine_ops (lists = 100)

### Supporting Tables

**strategy_metrics** - Performance metrics per strategy
- Fields: strategy_id (FK, unique), win_rate, avg_pnl, sharpe, max_drawdown
- Updated: timestamp field for last calculation

**factor_ic_history** - Information Coefficient tracking
- Fields: factor_name, ic_score, computed_at
- Purpose: Track predictive performance of factors over time

**system_metrics** - Operational and performance metrics
- Fields: metric_name, value, labels JSONB, timestamp
- Indexing: (metric_name, timestamp DESC) for time-series queries

**audit_log** - Immutable audit trail for business changes
- Fields: event_type, payload JSONB, created_at
- Indexing: created_at DESC for recent events lookup

**order_reconciliation** - Order discrepancy tracking
- Fields: order_id (FK), discrepancy JSONB, resolved boolean
- Purpose: Track and resolve order execution issues

**llm_cost_tracking** - LLM usage cost tracking
- Fields: date, tokens_used, cost_usd
- Purpose: Budget management and cost optimization

### Schema Versioning

- **v2**: Initial schema with basic tables
- **v3**: Added traceability indexes and strict schema validation
- **Constraints**: schema_version CHECK constraints on agent tables
- **Indexes**: trace_id indexes for agent_runs and agent_logs

## System Guarantees

### Determinism
- All writes go through SafeWriter (only authorized path)
- No hidden side effects or async background mutations
- Same input → same output, every time

### Idempotency
- Orders: idempotency_key prevents duplicate orders
- Events: idempotency_key prevents duplicate events  
- Streams: processed_events table ensures exactly-once processing

### Traceability
- trace_id spans entire system: Event → AgentRun → AgentLog → VectorMemory
- Any execution reconstructable from single trace ID
- Immutable audit_log for permanent change history

### Replayability (🔥 Critical Guarantee)
- Entire system rebuildable from events table
- Events contain all necessary data (no side-channel info)
- Disaster recovery = replay events + restore current positions

### Consistency Model
```
PostgreSQL (Source of Truth) → Redis Streams (Delivery) → Agents (Derived)
```
- Database = canonical state
- Streams = transport/fan-out, not storage
- Agents = consumers, never modify source truth

### Failure Isolation
| Component     | Failure Impact | Recovery Method            |
| ------------- | -------------- | -------------------------- |
| SafeWriter    | No new writes  | Restart service            |
| Redis Streams | No processing  | Replay events from DB      |
| Agent Service | No analysis    | Restart, reprocess pending |
| PostgreSQL    | System down    | Restore backup + replay    |

### Formal Invariants
1. Event Ordering: events.created_at monotonic per entity
2. Idempotency: idempotency_key unique across domain
3. Traceability: All trace_id values are valid UUIDs
4. Atomicity: Business write + event emit succeed/fail together
5. Immunity: audit_log and agent_runs never updated

## WebSocket Events

### Connection
```
URL: wss://your-app.onrender.com/ws/dashboard
Auth: None required in paper mode
Auto-reconnect with exponential backoff (1s → 30s cap)
```

### Message Envelope
```typescript
interface WsEnvelope {
  type: string;           // event type - determines routing
  timestamp: string;      // ISO 8601 UTC
  data: Record<string, unknown>;
}
```

### Event Types
- **market_tick** - Live price updates (~250ms per symbol)
- **signal** - New trading signal passed rule pipeline
- **order_update** - Order lifecycle changes (created, filled, cancelled)
- **agent_log** - Structured reasoning from ReasoningAgent
- **risk_alert** - Risk threshold crossed (drawdown, stream_lag, etc.)
- **regime_change** - Market regime changed (risk_on/risk_off/crisis)
- **notification** - System notifications (CRITICAL must be acknowledged)
- **learning_event** - Learning layer updates (IC weights, reflection, grading)
- **system_metric** - Health metrics (stream_lag, llm_cost, kill_switch_state)

===================================================================
10. DEVELOPMENT PATTERNS
===================================================================

## Agent Development Patterns

### New Agent Template
```python
from __future__ import annotations
import uuid
from typing import Any
from api.observability import log_structured
from api.events.bus import EventBus

class NewAgent:
    """Template for new agents with required patterns."""
    
    def __init__(self, redis_client: EventBus):
        self.redis = redis_client
        self.agent_id = "NewAgent"  # Must match agent_pool.name
        
    async def process_event(self, event_data: dict[str, Any]) -> None:
        """Main agent processing method."""
        trace_id = str(uuid.uuid4())
        
        try:
            # 1. Extract trace_id from incoming event if available
            incoming_trace_id = event_data.get("trace_id")
            
            # 2. Log start of processing
            log_structured("info", "agent processing started", 
                          agent=self.agent_id, 
                          trace_id=trace_id,
                          incoming_trace_id=incoming_trace_id)
            
            # 3. Process the event
            result = await self._do_work(event_data, trace_id)
            
            # 4. Publish results if needed
            if result:
                await self.redis.publish("output_stream", {
                    "type": "agent_result",
                    "data": result,
                    "trace_id": trace_id,
                    "agent_id": self.agent_id
                })
                
            log_structured("info", "agent processing completed", 
                          agent=self.agent_id, 
                          trace_id=trace_id)
                          
        except Exception as exc:
            log_structured("error", "agent processing failed", 
                          agent=self.agent_id, 
                          trace_id=trace_id,
                          exc_info=True)
            raise
            
    async def _do_work(self, event_data: dict[str, Any], trace_id: str) -> dict[str, Any]:
        """Override this method with agent-specific logic."""
        return {"status": "processed", "trace_id": trace_id}
```

### Required Agent Patterns
1. **Trace ID Propagation**: Always extract and propagate trace_id
2. **Structured Logging**: Use log_structured with exc_info=True for errors
3. **Event-Driven**: Never call other agents directly, use Redis streams
4. **Idempotency**: Handle duplicate events gracefully
5. **Error Handling**: Never swallow exceptions, always log with exc_info=True

## Database Development Patterns

### SafeWriter Usage
```python
from api.core.writer.safe_writer import SafeWriter
from api.database import get_async_session

async def create_business_record(data: dict[str, Any]) -> UUID:
    """Correct pattern for database writes."""
    async with get_async_session() as session:
        writer = SafeWriter(session)
        
        # SafeWriter handles validation, idempotency, and audit
        record_id = await writer.write(
            table="orders",
            data=data,
            schema_version="v3",
            source="order_service"
        )
        
        return record_id
```

### Schema Requirements
- **schema_version**: Always "v3" for new writes (upgraded from "v2")
- **source**: Service name that created the record
- **trace_id**: Include for traceable operations
- **idempotency_key**: For operations that must be exactly-once

## Redis Stream Patterns

### Publishing Events
```python
# Correct: Use positional arguments for xgroup_create
await redis.xgroup_create(stream, group, "$", mkstream=True)

# Correct: Include trace_id in all events
await redis.publish("stream_name", {
    "type": "event_type",
    "data": event_data,
    "trace_id": trace_id,
    "timestamp": datetime.now(timezone.utc).isoformat()
})
```

### Consumer Groups
- **analysis_agents**: Signal generation, risk assessment
- **execution_agents**: Order execution and position management  
- **learning_agents**: Performance analysis and optimization
- **monitoring_agents**: Health monitoring and alerting

## Testing Patterns

### Agent Testing
```python
import pytest
from api.events.bus import EventBus
from api.services.new_agent import NewAgent

@pytest.fixture
async def agent():
    redis = EventBus()
    return NewAgent(redis)

async def test_agent_processes_event(agent):
    """Test agent with trace ID propagation."""
    event_data = {
        "type": "test_event",
        "data": {"symbol": "BTC/USD"},
        "trace_id": "test-trace-123"
    }
    
    result = await agent.process_event(event_data)
    
    # Verify trace ID was preserved
    assert result["trace_id"] == "test-trace-123"
```

### Database Testing
```python
from tests.core.fake_session import FakeAsyncSession

async def test_safe_writer_idempotency():
    """Test that duplicate writes are handled correctly."""
    session = FakeAsyncSession()
    writer = SafeWriter(session)
    
    data = {"symbol": "BTC/USD", "side": "buy"}
    idempotency_key = "unique-key-123"
    
    # First write succeeds
    record_id_1 = await writer.write(
        table="orders",
        data=data,
        idempotency_key=idempotency_key,
        schema_version="v3",
        source="test"
    )
    
    # Second write returns same ID
    record_id_2 = await writer.write(
        table="orders", 
        data=data,
        idempotency_key=idempotency_key,
        schema_version="v3",
        source="test"
    )
    
    assert record_id_1 == record_id_2
```

## Configuration Management

### Environment Variables
```bash
# Agent Configuration (from api/config.py)
SIGNAL_EVERY_N_TICKS=10
GRADE_EVERY_N_FILLS=5
IC_UPDATE_EVERY_N_FILLS=10
REFLECT_EVERY_N_FILLS=10
REFLECTION_TRADE_THRESHOLD=20

# LLM Configuration  
LLM_PROVIDER=groq
LLM_TIMEOUT_SECONDS=15
LLM_MAX_RETRIES=2
LLM_FALLBACK_MODE=skip_reasoning
ANTHROPIC_DAILY_TOKEN_BUDGET=5000000
ANTHROPIC_COST_ALERT_USD=5.0

# Market Data Configuration
MARKET_DATA_PROVIDER=alpaca
MARKET_TICK_INTERVAL_SECONDS=10.0

# Alpaca Trading Configuration
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Redis Configuration
REDIS_URL=redis://localhost:6379

# Database Configuration
DATABASE_URL=postgresql://user:pass@localhost/db

# Application Configuration
FRONTEND_URL=http://localhost:3000
BROKER_MODE=paper
MAX_CONSUMER_LAG_ALERT=5000

# Groq Configuration
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
```

### Configuration Validation
```python
from pydantic import BaseSettings

# Actual configuration from api/config.py
class Settings(BaseSettings):
    DATABASE_URL: PostgresDsn | None = Field(default=None)
    REDIS_URL: str | None = Field(default=None)
    ANTHROPIC_API_KEY: str | None = Field(default=None)
    ANTHROPIC_DAILY_TOKEN_BUDGET: int = 5_000_000
    LLM_FALLBACK_MODE: str = "skip_reasoning"
    BROKER_MODE: str = "paper"
    LLM_TIMEOUT_SECONDS: int = 15
    LLM_MAX_RETRIES: int = 2
    REFLECTION_TRADE_THRESHOLD: int = 20
    MAX_CONSUMER_LAG_ALERT: int = 5_000
    ANTHROPIC_COST_ALERT_USD: float = 5.0
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Market data
    MARKET_DATA_PROVIDER: str = "alpaca"
    MARKET_TICK_INTERVAL_SECONDS: float = 10.0
    
    # Agent trigger thresholds
    SIGNAL_EVERY_N_TICKS: int = 10
    GRADE_EVERY_N_FILLS: int = 5
    IC_UPDATE_EVERY_N_FILLS: int = 10
    REFLECT_EVERY_N_FILLS: int = 10
    
    # LLM provider routing
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    
    # Alpaca configuration
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_PAPER: bool = True
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
```

## Error Handling Patterns

### Structured Error Response
```python
from fastapi import HTTPException

async def api_endpoint():
    try:
        result = await some_operation()
        return {"status": "success", "data": result}
    except ValueError as exc:
        log_structured("error", "validation failed", exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        log_structured("error", "unexpected error", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error") from None
```

### Circuit Breaker Pattern
```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5):
        self.failure_threshold = failure_threshold
        self.failure_count = 0
        self.last_failure_time = None
        
    async def call(self, func, *args, **kwargs):
        if self.is_open():
            raise Exception("Circuit breaker is open")
            
        try:
            result = await func(*args, **kwargs)
            self.reset()
            return result
        except Exception as exc:
            self.record_failure()
            raise
            
    def is_open(self) -> bool:
        return (self.failure_count >= self.failure_threshold and 
                time.time() - self.last_failure_time < 60)
```

===================================================================
11. SYSTEM VERIFICATION
===================================================================

### Redis Streams Verification
```bash
redis-cli xlen signals                       # > 0 within 30s of poller starting
redis-cli xlen decisions                     # > 0 shortly after  
redis-cli xlen graded_decisions              # > 0 shortly after
redis-cli keys "agent:status:*"              # should show current agents
```

### Database Verification
```bash
# Check database health and schema version
psql $DATABASE_URL -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agent_runs WHERE schema_version='v3';"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM vector_memory;"  # should show embeddings
psql $DATABASE_URL -c "SELECT name, is_active FROM strategies;"  # should show BTC_MOMENTUM_V3
```

### Application Structure Verification
```bash
# Verify key directories exist
ls api/services/agents/          # Should have reasoning_agent.py, pipeline_agents.py
ls api/routes/                   # Should have 13 route files
ls api/alembic/versions/         # Should have 3 migration files
ls tests/                       # Should have comprehensive test suite
```

### CI/CD Testing
```bash
# Run the exact CI/CD pipeline commands locally
ruff check . --fix               # Must show "All checks passed!"
ruff format --check .           # Must show "112 files already formatted"  
ruff check . --select=E9,F63,F7,F82  # Must show "All checks passed!"

# Run test suite
pytest tests/ -v --tb=short    # All tests should pass
```
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
