# Lessons Learned

When you make a mistake and get corrected, immediately add a rule 
to this file in this format:

## [date] — [Component Name] failure
- Mistake: [e.g., Agent generated a new UUID instead of propagating trace_id]
- Fix: [e.g., Always pull trace_id from the Redis stream header]
- Rule: **ALWAYS** use `log_structured()` from `api.observability` for all logging

**Anti-Pattern vs Pattern Documentation:**
- **Anti-Pattern**: What NOT to do (the mistake)
- **Pattern**: What TO do instead (the correct approach)

Then update CLAUDE.md if the lesson applies globally.

---

## [2025-03-29] — Multi-Agent Orchestrator failure
- Mistake: Used `print()` instead of structured logging for trade analysis results
- Fix: Replaced with `log_structured("info", "trade analysis result", ...)` 
- Rule: **ALWAYS** use `log_structured()` from `api.observability` for all logging

**Anti-Pattern**: `print(json.dumps(result, indent=2))`
**Pattern**: `log_structured("info", "trade analysis result", result=result)`

---

## [2025-03-29] — Stream Manager logging inconsistency
- Mistake: Used 20+ `logger.info/error/warning` calls instead of structured logging
- Fix: Migrated all to `log_structured()` with proper key=value format
- Rule: **NEVER** use `logger.*` in new code - always import and use `log_structured`

**Anti-Pattern**: `logger.error(f"Failed to read from stream {stream}: {e}")`
**Pattern**: `log_structured("error", "stream read failed", stream=stream, error=str(e))`

**Status**: 51 remaining logger calls need migration across other files

**Priority Files Remaining**:
- api/core/writer/safe_writer.py: 28 calls (critical database operations)
- api/routes/system_health.py: 6 calls (health checks)
- api/core/db/session.py: 5 calls (database sessions)
- api/services/multi_agent_orchestrator.py: 3 calls (agent coordination)

**Progress**: 26 logger calls migrated in this session (dashboard_v2, monitoring, metrics_aggregator)
