# Changelog

## [2026-06-01] — Cognitive brain hardening: walk-forward, governance, lineage, retention

### Added
- **Walk-forward validation** — `cognitive/backtest_gate.walk_forward` evaluates a candidate across several sequential market periods; `cognitive/challenger.review` adds a `walk_forward_consistent` check (candidate must beat baseline in ≥60% of folds) so a single-window fluke can't be promoted
- **News is genuinely backtested** — the gate accepts a per-bar sentiment series; `evolve(..., news=...)` threads it through both the in/out split and walk-forward (previously news was constant-0 and a news-weight proposal was inert)
- **Proposal governance** — `cognitive/governance.ProposalGovernor`: per-window quota, exact-duplicate dedup, and a reject cooldown that benches a target (novelty/retirement); new `ProposalStatus.BLOCKED`
- **Per-trade config lineage** — decision/execution/outcome events and the trace stamp `config_version` + `config_proposal_id`; `CognitiveLoop.merge()` records provenance
- **Event-stream retention** — `EventStream(max_events=…)` evicts oldest events with a monotonic `seq`; `dropped`/`emitted` surfaced in `health`
- `tests/core/test_cognitive_hardening.py` — retention, walk-forward, governance, lineage, and a risk-independence stream invariant (no EXECUTION without a RISK_GATE)

### Changed
- `CognitiveLoop.evolve` — governor admission gate before any backtest; threads news + walk-forward; records governor + scorecard outcomes
- `docs/troubleshooting/cognitive.md` — news-inert-in-backtest fix documented

## [2026-06-01] — Cognitive trading brain: deterministic GitOps-evolved loop

### Added
- `cognitive/` — a deterministic, event-stream-driven multi-agent cognitive brain that wires the full closed loop on one `EventStream`: agents → feature aggregation → math-only decision → hard risk gate → execution → attribution + multi-dimensional grading → observations → ProposalAgent → shadow backtest → challenger → GitOps PR
- Five cognitive specialists (News/Technical/Macro/Risk/Reasoning) as advisory-only modules with deterministic default scorers and an injectable LLM seam, discovered via a central `AgentRegistry`
- Deterministic decision engine `score = Σ signalᵢ·weightᵢ → BUY/SELL/HOLD` (no LLM/agent influence; the `risk` feature is a separate hard gate, never part of the score)
- `LearningEngine` that produces **observations only** (never edits config/weights) + `ImportanceTracker` metadata; first-class `ProposalAgent` with a `ProposalType` hierarchy (weight/prompt/tool/backtest/risk/feature) and a `ProposalScorecard` that learns success-rate by type
- Config-parameterized **paired shadow backtest** (`cognitive/backtest_gate.py`) producing `{pnl, sharpe, drawdown, false-positive}` deltas — the judge every proposal must clear; `cognitive/challenger.py` safety validator (sample size / overfit / risk impact / attribution consistency)
- `cognitive/gitops.py` — branch name, full config diff, evidence-rich PR body, bounds-safe config apply; **never auto-merges**
- Multi-dimensional grading (`cognitive/grading.py`) for trades (Direction/Risk/Execution/Timing → overall), agents, proposals, and config versions
- Per-trade `trace.py` ("why did we?") and `health.py` cognitive-wiring health, both pure reads of the stream
- `config/cognitive_config.json` — Git-versioned weights / thresholds / risk limits (data-not-code, bounds-validated)
- Read-only observability API `api/routes/cognitive.py` (`/cognitive/state|events|config|agents|trace/{id}|reseed`) driven entirely by the stream snapshot
- Tests: `tests/core/test_cognitive_*.py`, `tests/integration/test_cognitive_loop.py`, `tests/api/test_cognitive_routes.py`; docs in `cognitive/README.md` and `docs/troubleshooting/cognitive.md`

## [2026-05-23] — Decision provenance: grade trades with model awareness

### Added
- `api/services/llm_router.py` — `active_provider_and_model()` / `active_model_label()`: single source of truth for the `provider:model` label of the active LLM
- `FieldName.MODEL_USED` — payload key for the model that produced a decision
- Alembic migration `20260502_decision_provenance` — adds nullable `model_used`, `primary_edge`, `decision_cost_usd` columns to `trade_evaluations`
- Per-model **net ROI**: each decision's LLM cost (`decision_cost_usd`) travels with the trade; `GET /learning/model-performance` + the dashboard panel show LLM cost and net P&L (P&L − cost) per model
- `docs/AGENTS.md` — "LLM models — which model runs where" + "Decision provenance" sections

### Changed
- `ReasoningAgent` — stamps `model_used` (`provider:model`, or `fallback`) on every decision; flows to `agent_logs`, the Redis decision record, and the `decisions` stream
- `ExecutionEngine` / `fill_publisher` — `FillContext` carries `model_used` + `primary_edge` onto `trade_performance` / `trade_completed` events
- `trade_scorer.score_trade` + `db_helpers.persist_trade_evaluation` — record decision provenance on each `trade_evaluations` row
- `GET /learning/trades` (+ single-trade) — return `model_used` + `primary_edge`
- Frontend `LearningDashboard` — trade-detail modal shows the model + thesis behind each graded trade

## [2026-05-15] — Execution engine modularisation and observability fixes

### Added
- `api/services/execution/position_math.py` — pure PnL / position-delta functions extracted from `ExecutionEngine`; fully testable without mocking
- `api/services/execution/fill_publisher.py` — `FillContext` dataclass + `publish_fill_events()` replacing three near-identical stream-publishing blocks
- `api/services/execution/order_writer.py` — session-agnostic DB write helpers (`insert_pending_order`, `update_order_fill`, `upsert_position_db`, `insert_audit_log`)
- `tests/agents/test_position_math.py` — 35 unit tests covering all pure position-math functions
- `docs/known-issues.md` — living document for active and resolved bugs with mandatory regression-test references

### Changed
- `api/services/execution/execution_engine.py` — reduced from 1262 to ~560 lines; `process()` delegates to `_process_with_db()` / `_process_in_memory()`; backward-compat shims preserved for existing tests
- `api/services/execution/decision_utils.py` — `_as_score()` helper fixes two bugs: `"n/a"` no longer raises `ValueError` to DLQ, and `float(0.0)` is no longer promoted to `0.5`
- `docs/architecture.md` — updated stream chain table (now includes `executions`, `trade_performance`, `trade_lifecycle`, etc.) and repository structure (includes new execution sub-modules)
- `docs/index.md` — added link to `known-issues.md`
- `AGENTS.md` — fixed stale pytest command to use split subsets per CI requirements

### Fixed
- `GET /system/trading-mode` — now returns `UNKNOWN` when Redis is unreachable (was silently returning `TRADING`, which is fail-open)
- `GET /system/status` — stream lag now uses `DEFAULT_GROUP` constant instead of hardcoded `"trading_workers"` (was always showing "Consumer group not found" for healthy streams)
- `GET /system/status`, `GET /system/logs`, `GET /system/metrics` — guard on `is_db_available()` before creating SQLAlchemy sessions (were probing DB in memory mode)

## [2026-04-26] — Legacy frontend cleanup

### Removed
- Deleted the obsolete `frontend/src/legacy-pages` pages-router implementation (`dashboard-legacy`, `performance`, `logs`, `film-room`, and related bootstrap files).
- Removed unused mission-control UI components and health hooks that were only referenced by the deleted legacy pages.
- Removed the unused `HealthResponse`/`BotControlResponse` frontend type module and the stale `Header` component test tied to removed UI.
- Removed the unreferenced `frontend/src/components/obsidian-pro` prototype dashboard component set.
- Removed duplicate/unused frontend utility modules (`frontend/src/components/theme/ThemeToggle.tsx`, `frontend/src/lib/api.ts`, and `frontend/src/lib/fonts.ts`).

### Changed
- Simplified `frontend/tsconfig.json` by dropping the now-unneeded `src/legacy-pages/**/*` exclusion.
- Updated `frontend/vitest.config.ts` coverage includes to replace a deleted legacy `Header` target with a live dashboard runtime component.

## [2026-03-30] — Complete agent pipeline, price poller rewrite, and dashboard overhaul

### Added
- **Price Poller rewrite**: 5 writes per cycle (Redis cache, Redis stream, pub/sub, Postgres prices_snapshot upsert, Postgres system_metrics insert), price change calculation from previous Redis value, asyncio.timeout(8) on Alpaca fetches
- **7 pipeline agents fully implemented**: SignalGenerator, ReasoningAgent, GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent — all with full agent_runs lifecycle, dedup via processed_events, trace_id propagation, Redis + Postgres heartbeats
- **Stream chain**: market_events → signals → decisions → graded_decisions with proper classification logic at each stage
- **3 new dashboard API endpoints**: GET /dashboard/agents/status (agent status from Redis), GET /dashboard/system/metrics (stream lengths + DB counts), GET /dashboard/events/recent (last 10 events)
- **Frontend PipelineHealthBar component**: visual stream flow with arrow visualization (market_events → signals → decisions → graded_decisions)
- **Frontend AgentsSection**: polls /api/dashboard/agents/status every 10s, shows agent status with color-coded dots (ACTIVE=green, STALE=amber, ERROR=red, WAITING=gray)
- **Frontend SystemSection**: replaced WebSocket status with SSE status, shows pipeline metrics via 6 stream cards, recent events table
- Added "market_events", "decisions", "graded_decisions" to EventBus STREAMS tuple

### Fixed
- Signal classification logic: STRONG_MOMENTUM (≥3%), MOMENTUM (≥1.5%), PRICE_UPDATE (else)
- Agent stream chain: agents now listen to correct streams (was wrong stream names before)
- Test mocks for AsyncSessionFactory using proper async context managers
- LLM router test using patch.dict for _PROVIDERS to avoid groq import
- test_no_unknown_ids updated for JSON-structured log output
- All 117 tests passing, 0 failures
- Full CI/CD compliance: ruff check, ruff format, critical error checks all passing

### Architecture
- All agents use shared helper pattern: _ensure_agent_pool_id, dedup check, agent_runs create/complete/fail, agent_logs, heartbeats
- ReasoningAgent consolidated into pipeline_agents.py (single import point)
- Postgres tables created safely via comprehensive SQL script with IF NOT EXISTS guards

## [2026-03-28] — Project documentation and Claude Code setup

### Added
- .claudaignore file to exclude build artifacts and sensitive files
- CHANGELOG.md with current project state and remaining tasks
- CLAUDE.md with complete architecture documentation and coding rules
- .claude/settings.json with permissions for safe automated commands
- docs/AGENTS.md with agent implementation guidelines

### Verified
- All documentation files created and properly formatted
- Claude Code permissions configured to allow development commands while blocking destructive operations

### Remaining
- Real embedding model not wired into REFLECTION_AGENT (zero vector placeholder)
- REASONING_AGENT uses rule-based logic, no LLM yet
- IC_UPDATER not executing paper trades yet
- NOTIFICATION_AGENT not sending Slack/email yet
- verify_deployment.sh not been run against production yet

## [2026-03-28] — Initial architectural overhaul

### Added
- price_poller as standalone Render worker service
- REST endpoint GET /api/v1/prices with Redis cache + Postgres fallback
- SSE endpoint GET /api/v1/prices/stream replacing WebSocket
- GET /api/v1/agents/status endpoint
- Canonical schema tables: strategies, orders, positions, trade_performance,
  events, processed_events, audit_log, schema_write_audit, agent_pool,
  agent_runs, agent_logs, agent_grades, vector_memory, system_metrics
- prices_snapshot and agent_heartbeats tables
- Exactly-once processing via processed_events in all 7 agents
- trace_id propagation through full agent pipeline
- agent_runs and agent_logs writes on every agent execution
- Frontend REST on mount + SSE live updates
- Skeleton loaders replacing "--" placeholders
- CLAUDE.md with full architecture documentation

### Fixed
- Prices showing "--" — was browser-triggered, now background worker
- Agents stuck at WAITING 0 events — stream name mismatches corrected
- idempotency_key using timestamp — changed to trace_id
- seed migration using gen_random_uuid() — changed to hardcoded UUIDs

### Remaining
- Real embedding model not wired into REFLECTION_AGENT (zero vector placeholder)
- REASONING_AGENT uses rule-based logic, no LLM yet
- IC_UPDATER not executing paper trades yet
- NOTIFICATION_AGENT not sending Slack/email yet
- verify_deployment.sh not been run against production yet
