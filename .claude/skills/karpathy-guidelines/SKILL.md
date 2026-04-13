---
name: karpathy-guidelines
description: Four behavioral guardrails for every coding task — think first, stay simple, change surgically, verify goals. Preload into any agent to reduce silent assumptions and scope creep.
user-invocable: false
---

# Karpathy Guidelines — Trading Control Edition

Apply these four principles to every task before writing a single line.

---

## 1. Think Before Coding
**Don't assume. Surface confusion first.**

Before implementing, state your interpretation aloud. If there are two valid readings, name both and ask which is intended.

Trading-control specific traps:
- "Add signal validation" → local schema check OR Alpaca pre-flight check? Ask.
- "Fix the order bug" → wrong quantity, wrong side, wrong idempotency key? Reproduce it first.
- "Update the agent" → which of the 7 agents, and which stream direction? Confirm.
- Any DB change → verify whether it touches `agent_runs`/`events` (INTEGER pk constraint).

**Rule**: If you have to guess at scope, ask instead.

---

## 2. Simplicity First
**Minimum code. Nothing speculative.**

Implement exactly what was asked. The senior-engineer test: *"Would a good engineer call this overcomplicated?"*

Trading-control specific traps:
- Adding Redis caching when a direct DB query was asked for
- Creating a new base class when a single function suffices
- Adding new schema columns "while you're in there"
- Wrapping a one-time query in a reusable service layer nobody requested
- Adding error-handling for states that cannot occur inside the system

**Rule**: Three similar lines of code is better than a premature abstraction.

---

## 3. Surgical Changes
**Touch only what you must. Clean up only your own mess.**

When editing a file, match its existing style exactly. Only remove code your changes made orphaned — do not refactor unrelated logic.

Trading-control specific traps:
- Fixing a `signal_generator.py` bug then refactoring its heartbeat calls
- Updating a Redis key constant then "cleaning up" nearby unrelated keys
- Fixing a schema INSERT then renaming variables elsewhere in the function
- Adding a new route then reorganising the imports across the whole router file

**Rule**: The diff should be the smallest possible change that solves the problem.

---

## 4. Goal-Driven Execution
**Define success criteria. Loop until verified.**

Convert the task into a measurable outcome before starting. For any non-trivial task:

```
Goal: <one sentence — what does "done" look like?>
Steps:
  1. ...
  2. ...
Verification: <command or test that proves it works>
```

Trading-control specific verification:
- Schema changes → `pytest tests/core/test_production_schema_guardrails.py -v`
- Agent changes → `pytest tests/agents/test_{agent_name}*.py -v`
- API changes → `ruff check . --fix && pytest tests/api/ -v`
- Any push → `ruff check . && ruff format --check . && pytest tests/ -v`

**Rule**: Don't report done until the verification command passes.
