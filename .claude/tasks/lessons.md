# Lessons Learned

When you make a mistake and get corrected, immediately add a rule 
to this file in this format:

## [date] — [Component Name] failure
- Mistake: [e.g., Agent generated a new UUID instead of propagating trace_id]
- Fix: [e.g., Always pull trace_id from the Redis stream header]
- Rule: **NEVER** use `uuid4()` inside an agent's `process_event` loop.

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
