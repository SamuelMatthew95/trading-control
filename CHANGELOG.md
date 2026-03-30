# Changelog

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
