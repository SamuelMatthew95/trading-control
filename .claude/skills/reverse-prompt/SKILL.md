---
name: reverse-prompt
description: Before starting any complex task, ask targeted clarifying questions until the scope is unambiguous. Invoke at the start of multi-step work or whenever the request has two or more valid interpretations.
user-invocable: true
argument-hint: [task description]
---

Before writing any code, ask the following questions relevant to the task type. Do NOT start implementing until you have answers.

<clarification_questions>

  <scope>
  - What is the exact deliverable? (new file, edit to existing file, both?)
  - Which of the 7 agents does this touch, if any?
  - Which Redis streams are affected (input / output)?
  </scope>

  <schema_impact>
  - Does this touch agent_runs or events tables? (INTEGER pk constraint applies)
  - Does this add new DB columns? (migration required)
  - Does this add new Redis keys? (must go in api/constants.py)
  </schema_impact>

  <testing>
  - Is there an existing test file this should extend, or is a new one needed?
  - What is the verifiable success criterion — which pytest command proves it works?
  </testing>

  <constraints>
  - Are there edge cases that should NOT be handled (keep it simple)?
  - Should existing behaviour be preserved exactly, or is a behaviour change acceptable?
  </constraints>

</clarification_questions>

Once you have answers, state a one-sentence goal and a numbered plan before touching any files.

---

## Example of great output

**Input:** "Add retry logic to the execution engine"

**Questions asked:**
```
Before I start, I need to clarify a few things:

1. Scope: Should retry logic apply to Alpaca API calls only, or also to Redis
   stream publishes? Both have different failure modes.

2. Schema impact: Should retry attempts be logged to agent_runs or agent_logs?
   If yes, that touches execution_time_ms and source columns.

3. Testing: Is there an existing tests/agents/test_execution_engine.py to extend,
   or should I create one?

4. Constraints: Is there a max retry count already defined somewhere, or should
   I introduce a new constant in api/constants.py?
```

**After answers — goal + plan stated before any code:**
```
Goal: Add exponential-backoff retry (max 3 attempts) to Alpaca submit_order()
calls only, logging each retry attempt via log_structured().

Plan:
1. Add MAX_ORDER_RETRIES = 3 to api/constants.py
2. Wrap submit_order() in api/agents/execution_engine.py with retry loop
3. Extend tests/agents/test_execution_engine.py with retry scenario

Verification: pytest tests/agents/test_execution_engine.py -v --tb=short
```
