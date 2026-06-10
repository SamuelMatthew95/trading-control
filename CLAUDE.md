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

## Production DB Schema Reality (CRITICAL — Read Before Any INSERT)

The live PostgreSQL DB was created **before** the Alembic migration system.
Several tables have types and constraints that differ from what ORM models assume.

### Tables with INTEGER primary keys (NOT UUID)
```
agent_runs   id INTEGER  nextval('agent_runs_id_seq')
events       id INTEGER  nextval('events_id_seq')
```
**Rule**: Never pass `id` in the INSERT column list for these tables.
Use `RETURNING id` and store the result as `db_run_id` (integer).

```python
# CORRECT pattern for agent_runs / events
result = await session.execute(text("""
    INSERT INTO agent_runs (strategy_id, trace_id, source, schema_version, ...)
    VALUES (:strategy_id, :trace_id, :source, :schema_version, ...)
    RETURNING id
"""), {...})
db_run_id = result.first()[0]  # integer from sequence

# Later UPDATE uses db_run_id (integer), NOT run_id (UUID)
await session.execute(text(
    "UPDATE agent_runs SET status='completed' WHERE id=:id"
), {"id": db_run_id})
```

### Mandatory columns added by migration 20260407
These were absent in the pre-migration schema. All INSERTs must include them:
```
agent_runs   source VARCHAR(64)     — who wrote the row (e.g. AGENT_SIGNAL)
agent_runs   run_type VARCHAR(32)   — defaults to 'analysis' in DB
agent_runs   execution_time_ms INT  — nullable, written in success UPDATE
agent_logs   source VARCHAR(64)     — writer identity
agent_grades source VARCHAR(64)     — writer identity
events       data JSONB             — signal/event payload
events       idempotency_key VARCHAR(255) + UNIQUE INDEX
events       processed BOOLEAN      — defaults to false
events       schema_version VARCHAR(16)
```

### agent_grades NOT NULL constraints
`agent_id` and `agent_run_id` were created NOT NULL in the pre-migration schema.
Migration 20260407 drops both to nullable. `write_grade_to_db()` omits them
(NULL is valid). `signal_generator.py` passes `agent_pool_id or None`.

### Correct INSERT pattern — events (with dedup)
```sql
INSERT INTO events (event_type, entity_type, data, idempotency_key, source, schema_version)
VALUES ('signal.generated', 'signal', :data, :idem_key, :source, :schema_version)
ON CONFLICT (idempotency_key) DO NOTHING
```

### Guardrail tests (always run these)
```
tests/core/test_production_schema_guardrails.py  — source-code inspection
tests/core/test_field_name_guardrails.py         — enforces FieldName enum on all CLEAN_FILES
tests/agents/test_signal_generator_db_writes.py  — functional SQL capture
tests/agents/test_signal_generator_schema_fix.py — regression for column names
```

## Critical Anti-Patterns (NEVER Do These)
- ❌ `INSERT INTO agent_runs (id, ...)` → id is INTEGER, never pass UUID; use RETURNING id
- ❌ `"id": run_id` in UPDATE params for agent_runs → use `"id": db_run_id` (integer)
- ❌ `log_structured("error", "msg", error=str(exc))` → Use `exc_info=True`
- ❌ `redis.xgroup_create(stream, group, id="$", mkstream=True)` → Use positional args
- ❌ `async def endpoint(service=Depends(get_service))` → Use `Annotated[Service, Depends(...)]`
- ❌ `raise HTTPException(str(e))` → Add `from None`
- ❌ Missing imports for types → Always import what you use
- ❌ Hardcoded Redis keys anywhere → Use constants from `api/constants.py`
- ❌ Hardcoded TTL values (`ex=30`, `ex=90000`) → Use named constants
- ❌ String-literal dict keys for event payloads (`data.get("side")`, `pos["symbol"]`) → Use `FieldName` enum from `api/constants.py`
- ❌ Bare constants defined in a service/route file (`CRITICAL_LAG_MS = 5000`) → Cross-cutting values live in `api/constants.py` (see placement rule in `api/CLAUDE.md`)
- ❌ Inline imports inside functions → Imports go at file top; circular-import breaks and optional-dep loads are the only exceptions and MUST carry `# noqa: PLC0415` (enforced by ruff)

## Event Payload Field Access (CRITICAL — no raw string keys, ENFORCED BY CI)

All event / DB-row / Redis-message dict access must go through the
`FieldName` StrEnum in `api/constants.py`. Raw string keys silently break
when a payload field is renamed; producer/consumer drift becomes an invisible
bug the type checker can't catch.

`FieldName` is a **comprehensive registry** (~720 members) — a full
raw-string sweep of `api/` registered every payload dict key. Before adding a
member, check it does not already exist.

```python
from api.constants import FieldName

# ❌ WRONG — string literals
side = data.get("side") or data.get("action")
symbol = pos["symbol"]
trace = event.get("trace_id")
payload = {"symbol": s, "side": "buy", "trace_id": tid}

# ✅ RIGHT — FieldName enum (StrEnum, serializes to the same string)
side = data.get(FieldName.SIDE) or data.get(FieldName.ACTION)
symbol = pos[FieldName.SYMBOL]
trace = event.get(FieldName.TRACE_ID)
payload = {FieldName.SYMBOL: s, FieldName.SIDE: "buy", FieldName.TRACE_ID: tid}
```

### Enforcement: the CLEAN_FILES ratchet
`tests/core/test_field_name_guardrails.py` does an AST scan and hard-fails CI
whenever a file on `CLEAN_FILES` re-introduces a raw string FieldName key.
The list can only grow — removing a file is a regression.

The scan catches the key string **anywhere on a line**, in every access form:
`d.get("k")`, `d.pop("k")`, `d.setdefault("k")`, `d["k"]`, `{"k": v}` dict
literals, and `"k" in d` membership tests.

When you sweep a new file clean of raw-string FieldName keys:
1. Replace every raw string with the corresponding `FieldName.NAME`.
2. Verify with:
   ```
   python -c "import ast; ast.parse(open('<path>').read()); print('OK')"
   ```
3. Add the file path to the `CLEAN_FILES` set in
   `tests/core/test_field_name_guardrails.py`.
4. Run `pytest tests/core/test_field_name_guardrails.py -v` — it must pass.

### Adding a new field
Add it to `class FieldName(StrEnum)` in `api/constants.py` FIRST (member name
MUST equal value in uppercase — `FOO = "foo"`; the test
`test_names_match_values` enforces this). Then reference `FieldName.FOO`
everywhere you read/write the payload key.

### Legitimate exceptions (keep as raw strings)
- **SQL bind parameters**: keys passed as the 2nd arg to
  `session.execute(text("... :name ..."), {...})` must match `:name`
  placeholders. The guardrail exempts dict-LITERAL keys (and `"k" in d`
  membership) in files listed in `SQL_BIND_HEAVY_FILES`, but READ operations
  (`.get`, `.pop`, `.setdefault`, `[...]`) are always enforced everywhere.
- **SQL schema-detection column names**: `"created_at" in available_columns`
  and similar probe DB column identifiers used to build `text()` SQL — they
  are not payload-dict keys. Kept raw; the membership check is relaxed for
  `SQL_BIND_HEAVY_FILES` precisely for this.
- **Infrastructure / library API kwargs** (`api/database.py`): SQLAlchemy
  engine kwargs (`pool_size`, `connect_args`), asyncpg `server_settings`, and
  Postgres table identifiers are library/schema API — not agent payload keys.
  `api/database.py` is in `SQL_BIND_HEAVY_FILES`; its dict-key strings stay
  raw. Routing a `StrEnum` key through asyncpg's C connection layer is an
  untested path — keep these literal.
- **SQLAlchemy `.values(col=...)` and `set_={col: ...}` kwargs**: column
  names, not payload keys. Not caught by the guardrail anyway.
- **Function keyword arguments** (`log_structured("info", "msg", symbol=x)`):
  not dict keys. Not caught.

## Redis Key Constants (All Redis Keys Live in api/constants.py)
```python
from api.constants import (
    REDIS_KEY_KILL_SWITCH,          # "kill_switch:active"
    REDIS_KEY_KILL_SWITCH_UPDATED_AT, # "kill_switch:updated_at"
    REDIS_KEY_IC_WEIGHTS,           # "alpha:ic_weights"
    REDIS_KEY_PRICES,               # "prices:{symbol}" — use .format(symbol=symbol)
    REDIS_KEY_WORKER_HEARTBEAT,     # "worker:heartbeat"
    REDIS_PRICES_TTL_SECONDS,       # 150s — price cache lifetime (must exceed poll interval)
    REDIS_IC_WEIGHTS_TTL_SECONDS,   # 90000s (~25h) — IC weights survive overnight
)
# Prices key usage:
await redis.get(REDIS_KEY_PRICES.format(symbol="BTC/USD"))
pipe.set(REDIS_KEY_PRICES.format(symbol=symbol), payload, ex=REDIS_PRICES_TTL_SECONDS)
# Kill switch usage:
if await redis.get(REDIS_KEY_KILL_SWITCH) == "1": raise RuntimeError("KillSwitchActive")
```

## Shared Heartbeat Module (api/services/agent_heartbeat.py)
All agents write heartbeats via the shared module — never write directly to Redis.
```python
from api.services.agent_heartbeat import write_heartbeat
# Writes to BOTH Redis (AGENT_HEARTBEAT_TTL_SECONDS TTL) and agent_heartbeats Postgres table
await write_heartbeat(redis, AGENT_SIGNAL, last_event="processed BTC/USD tick")
```
Benefit: Postgres `agent_heartbeats` table retains history even after Redis key expiry.

## CI/CD Verification (MANDATORY before every push)

Run these in order — mirrors `.github/workflows/backend-ci.yml` exactly:
```bash
ruff check . --fix
ruff format --check .
ruff check . --select=E9,F63,F7,F82
pytest tests/core tests/api -v --tb=short     # CI "unit tests" step
pytest tests/integration -v --tb=short        # CI "integration tests" step
pytest tests/agents -v --tb=short             # local only — not in CI but catches regressions
```

**Never use `pytest tests/` alone** — CI runs two separate subset commands, so
ordering-sensitive failures only surface when you run them split, not combined.

### Test Isolation Rule (CRITICAL — prevents ghost-state CI failures)
`_db_available` and `get_runtime_store()` are module-level globals. Agents in memory mode
write to the global `InMemoryStore`. Tests that call `agent.process()` without resetting
the store pollute every subsequent test.

`tests/conftest.py` resets both before every test automatically:
```python
@pytest.fixture(autouse=True)
def _reset_runtime_state():
    set_runtime_store(InMemoryStore())
    set_db_available(False)
```
- Never call `set_db_available(True)` globally in a test — monkeypatch the module instead
- Never assume the store is empty without calling `set_runtime_store(InMemoryStore())` first
- See `memory-cicd.md` for the full catalogue of known CI failure patterns

## Agent Name Constants (CRITICAL — Prevents Dashboard Bugs)
All agent names live in `api/constants.py`. NEVER use string literals for agent names.

```python
from api.constants import (
    AGENT_SIGNAL, AGENT_REASONING, ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    AGENT_HEARTBEAT_TTL_SECONDS,   # Redis key TTL — 300s (5 min)
    AGENT_STALE_THRESHOLD_SECONDS, # Show STALE if last_seen > 120s
)
# Agents write heartbeat:
await redis.set(REDIS_AGENT_STATUS_KEY.format(name=AGENT_SIGNAL), ..., ex=AGENT_HEARTBEAT_TTL_SECONDS)
# Dashboard reads:
keys = [REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES]
# Dashboard stale check:
status = "STALE" if age > AGENT_STALE_THRESHOLD_SECONDS else data["status"]
```

Names are SCREAMING_SNAKE_CASE (`SIGNAL_AGENT`, not `SignalGenerator`).

### Heartbeat timing invariant
`AGENT_HEARTBEAT_TTL_SECONDS` > `AGENT_STALE_THRESHOLD_SECONDS` always — otherwise a slow-but-running
agent expires before the dashboard can ever show it as STALE (goes straight to "offline").

## Self-Evolving Cognition Loop (LLM-driven, prompt evolves)

Each cognition stage that needs judgement is LLM-powered with its own prompt; the
loop closes on itself and the reasoning prompt **evolves**:

```
signal → ReasoningAgent (LLM; constitution + ADAPTIVE DIRECTIVE + tool-governed prompt)
       → decision (records tools_used + model_used)
       → ExecutionEngine → trade closes (realized PnL)
       → GradeAgent (deterministic 4-D score) ── attributes PnL to each tool (alpha)
                                            └── emits backtest-backed proposals
       → ReflectionAgent (LLM) → StrategyProposer (LLM)
              ├─ ranks hypotheses → PARAMETER/CODE/NEW_AGENT/REGIME proposals
              └─ LLM drafts an improved adaptive directive → PROMPT_EVOLUTION proposal
       → ProposalApplier → PromptStore.set_directive() (versioned, history-capped)
       → the NEXT ReasoningAgent decision assembles the evolved directive → …
```

Key invariants:
- **Constitution is immutable.** The evolved directive is `challenger_variant`,
  assembled BENEATH it; safety/capital-preservation can never be weakened.
- **Tools are graded by outcome.** `GradeAgent` folds realized PnL into each
  tool's alpha; negative-alpha tools are filtered from the prompt AND proposed
  for disable (closes the tool loop). New tools are registered + governable.
- **Proposals are backtest-backed.** Every `GradeAgent` proposal carries a
  measured `ReplayHarness` verdict (win rate / PnL / Sharpe / drawdown / FPR)
  over the recent trade buffer — evidence, not a blind guess.
- **Proposal routing (ProposalApplier handler-map, never edits code):**
  `PARAMETER_CHANGE` → config-only auto-PR (`GitOpsPublisher`, edits the
  bounds-validated `config/param_overrides.json` — same file the GitHub Action
  path edits — loaded by `api/constants.py` at import); `NEW_AGENT` → spawn a shadow challenger
  **dynamically** via `ChallengerSpawner` when its strategy is in
  `backtest.strategies.STRATEGIES` (config, no deploy), else file an issue;
  `CODE_CHANGE`/`REGIME_ADJUSTMENT` → GitHub issue for human design;
  `PROMPT_EVOLUTION` → prompt store; `TOOL_GOVERNANCE` → disables the flagged
  tools in the in-process `ToolRegistry` (`set_enabled(name, False)`);
  weight/suspension/retirement → Redis control plane. GitOps is gated on
  `GITHUB_TOKEN` (Render) — dry-run locally. The proposal queue UI badges each
  row's destination ("On Approve" column → `frontend/src/lib/proposal-routing.ts`).
- **Fail closed.** `LLM_FALLBACK_MODE` defaults to `reject_signal`: when the
  reasoning LLM is down, the agent emits `REJECT` (no order), never a naive
  momentum buy. Provider throttle degrades reason→instruct model, not to a
  phantom trade. Cooldown + signal-dedup + self-critique toggle bound spend.
- Flags: `PROMPT_EVOLUTION_ENABLED` / `PROMPT_EVOLUTION_AUTO_APPLY`,
  `REASONING_COOLDOWN_SECONDS` / `REASONING_DEDUP_PRICE_PCT` /
  `REASONING_SELF_CRITIQUE_ENABLED` (all `api/config.py`).

## Data Fetch Pipeline (PostgreSQL → API → Frontend)
How the dashboard is hydrated on load / reconnect:

| Data | Source Table | API Layer |
|------|-------------|-----------|
| `orders` | `orders` ORM | `MetricsAggregator.get_raw_snapshot()` |
| `positions` | `positions` ORM | `MetricsAggregator.get_raw_snapshot()` |
| `agent_logs` | `agent_logs` (schema-detected) | `MetricsAggregator.get_raw_snapshot()` |
| `learning_events` | `agent_grades` | `MetricsAggregator.get_raw_snapshot()` |
| `proposals` | `agent_logs WHERE log_type='proposal'` | `MetricsAggregator.get_raw_snapshot()` |
| `trade_feed` | `trade_lifecycle` | `MetricsAggregator.get_raw_snapshot()` |
| `agent_statuses` | Redis `REDIS_AGENT_STATUS_KEY.format(name=n)` | `/dashboard/state` enrichment |
| `ic_weights` | Redis `REDIS_KEY_IC_WEIGHTS` | `/dashboard/state` enrichment |
| `prices` | Redis `REDIS_KEY_PRICES.format(symbol=s)` | `/dashboard/state` enrichment |
| `notifications` (REST catch-up) | Redis list `notifications:recent` (cap 20) | `GET /notifications` |
| `decisions` (REST catch-up) | Redis list `decisions:recent` (cap 50) | `GET /decisions` |
| `llm_metrics` (durable) | Redis hash `llm:metrics` | `GET /llm/health` (`redis_metrics` block) |
| `tools` + `suggestions` + `attribution` | in-process `ToolRegistry` (seeded catalog; telemetry + realized-PnL alpha from `GradeAgent`) | `GET /dashboard/tools` → `ToolGovernancePanel` |
| `prompt_evolution` (active directive + version + history) | Redis `REDIS_KEY_PROMPT_DIRECTIVE` via `PromptStore` | `GET /dashboard/prompt-evolution` → `PromptEvolutionPanel` |
| `proposals` (voteable, backtest-backed) | `agent_logs WHERE log_type='proposal'` / memory `event_history` (each carries a `backtest` `ReplayMetrics` block) | `/dashboard/state` → `/dashboard/proposals` page |

REST hydration endpoint: `GET /dashboard/state`
Guardrail tests: `tests/core/test_data_fetch_guardrails.py` + `tests/core/test_agent_constants.py`

### Redis-backed REST persistence (memory-mode UI)
`api/services/redis_store.RedisStore` writes notifications, decisions, and
LLM call outcomes to Redis lists/hashes so the dashboard works without
Postgres. Producers:

| Producer | Writes |
|---|---|
| `ReasoningAgent.process()` | every decision → `decisions:recent`; buy/sell → `notifications:recent` |
| `NotificationAgent.process()` | every fired notification → `notifications:recent` (mirror) |
| `LLMMetricsCollector.record_*` | fire-and-forget → `llm:metrics` hash |

Install once at startup: `set_redis_store(RedisStore(redis_client))`.
Consumers (REST routes) read via `get_redis_store()` — graceful no-op when
the singleton is `None`.

### Memory mode (`USE_MEMORY_MODE=true`)
Operator-declared "no Postgres" runtime. Effects:
- `api/main.py` lifespan skips DB init entirely (no DNS retries).
- `api/routes/health.py::_database_ready()` short-circuits to `False` — no
  `database health check failed` warnings on every probe.
- `/health` returns `database: "memory"` (not "disconnected"); `/readiness`
  is "ready" iff Redis is up.
- Frontend dashboard hydrates from the Redis-backed REST endpoints above
  on mount + every WebSocket reconnect (see `frontend/CLAUDE.md`).

## Claude Code Workflow
- **Commits**: One commit per file — never bundle multiple files into one commit
- **Complex tasks**: Start in plan mode (`/plan`) before making changes
- **Context**: Run `/compact` manually when context reaches ~50% usage
- **Personal overrides**: Create `CLAUDE.local.md` at repo root (git-ignored) for local preferences
- **Specialized agents**: Use `.claude/agents/` — `ci-guard` (CI pipeline), `db-migrator` (Alembic), `test-writer` (pytest)
- **Reusable skills**: Use `.claude/skills/` — `run-ci` (full pipeline), `schema-check` (schema audit), `karpathy-guidelines` (think/simplify/surgical/verify), `reverse-prompt` (clarify before coding)
- **XML tags**: Use `<tags>` in prompts with 2+ components — Claude reads them with greater precision
- **Subdirectory context**: `api/CLAUDE.md` and `frontend/CLAUDE.md` load lazily when working in those dirs
- **Bug log (MANDATORY)**: Every bug fix must update `docs/troubleshooting/<subsystem>.md` in the same commit — no separate prompt needed. Files: `notifications.md`, `execution-engine.md`, `system-routes.md`. New subsystem → new file + update `docs/troubleshooting/README.md`. Format and full rule in `memory-cicd.md`.

## Additional Rules (Always Loaded)
@./.claude/rules/memory-trading.md     # Alpaca trading specifics
@./.claude/rules/memory-agents.md      # Agent hand-off protocols  
@./.claude/rules/memory-logging.md     # Trace ID & logging standards
@./.claude/rules/memory-cicd.md       # CI/CD patterns and fixes
@./.claude/rules/memory-storage.md    # Storage layer rules — Redis KV vs Streams vs Postgres vs InMemoryStore
