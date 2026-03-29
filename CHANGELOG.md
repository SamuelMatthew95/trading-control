# Changelog

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
