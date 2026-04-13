---
name: schema-check
description: Validates that Python files comply with trading-control DB schema rules — v3 schema_version, source column, INTEGER pks, no hardcoded Redis keys.
allowed-tools: Grep, Read, Bash
---

Audit the codebase for schema compliance violations. Check each rule and report file:line for every hit.

## 1. INTEGER PK violation — id in INSERT for agent_runs/events
```
Grep pattern: INSERT INTO (agent_runs|events)[^)]*\bid\b
```
Any match is a bug — `id` is a sequence, never pass it.

## 2. Missing schema_version='v3' in SafeWriter calls
```
Grep pattern: writer\.write\(
```
For each match, verify `schema_version` key is present in the data dict.

## 3. Missing source column in agent_runs/events INSERTs
```
Grep pattern: INSERT INTO (agent_runs|events|agent_logs|agent_grades)
```
Verify `source` is in the column list.

## 4. Hardcoded Redis keys (must use constants from api/constants.py)
```
Grep pattern: redis\.(get|set|hset|setex)\s*\(\s*f?["'](?!{)
```
Any string literal key that isn't from a constant is a violation.

## 5. Hardcoded TTL values
```
Grep pattern: ex=\d+(?!\s*#)
```
TTLs must use named constants (REDIS_PRICES_TTL_SECONDS, etc.).

## Run guardrail tests
```bash
pytest tests/core/test_production_schema_guardrails.py -v --tb=short
pytest tests/agents/test_signal_generator_db_writes.py -v --tb=short
```

Report: list all violations, then test results. Zero violations = ✅ compliant.

---

## Example of great output

**Violations found:**
```
❌ api/agents/reasoning_agent.py:83 — INTEGER PK violation
   INSERT INTO agent_runs (id, strategy_id, ...) — remove `id` from column list

❌ api/routes/trading.py:124 — Hardcoded Redis key
   await redis.set("kill_switch:active", "1") — use REDIS_KEY_KILL_SWITCH

Guardrail tests:
  ✅ test_production_schema_guardrails.py — 12 passed
  ❌ test_signal_generator_db_writes.py — 1 failed
     AssertionError: 'id' found in INSERT column list

2 violations. Fix before pushing.
```

**Clean audit:**
```
✅ No INTEGER PK violations
✅ All SafeWriter calls include schema_version='v3'
✅ All INSERTs include source column
✅ No hardcoded Redis keys
✅ No hardcoded TTL values

Guardrail tests:
  ✅ test_production_schema_guardrails.py — 12 passed
  ✅ test_signal_generator_db_writes.py — 8 passed

Schema compliant — safe to push.
```
