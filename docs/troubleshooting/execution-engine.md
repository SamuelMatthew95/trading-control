# Execution Engine Troubleshooting

## Score parsing — `"n/a"` sends decisions to DLQ

**Symptom:** Hold decisions from `ReasoningAgent` land in the dead-letter queue instead of producing an idle heartbeat.

**Root cause:** `float("n/a")` raises `ValueError`. The engine treated every non-numeric score as fatal.

**Fix:** `_as_score()` in `api/services/execution/decision_utils.py` catches parse errors and returns `None`, falling through to the next score key and ultimately defaulting to `0.5`.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_extract_scores_malformed_string_falls_through`

---

## Score parsing — `0.0` confidence promoted to `0.5`

**Symptom:** Trades execute at `signal_confidence = 0.5` even when the decision explicitly set it to `0.0` (the minimum valid score).

**Root cause:** Guard was `if score:` — falsy for Python `float(0.0)`.

**Fix:** `_as_score()` checks `None` and `""` explicitly, so `0.0` and `"0.0"` are preserved.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_extract_scores_python_float_zero_stays_zero`

---

## Decisions backlog — high count, zero executions

**Symptom:** Dashboard shows hundreds of decisions with zero corresponding trade executions.

**Check in order:**

1. `GET /system/trading-mode` → `status: KILL_SWITCH` means the kill switch is engaged.
2. `GET /system/trading-mode` → `status: PAUSED` means the circuit breaker is active. Clear it: `POST /system/trading-mode {"status": "TRADING"}`.
3. Agent heartbeat for `ExecutionEngine` shows STALE or OFFLINE — the process is not running.
4. Check `signal_confidence` values in recent decisions. If they are all below the execution gate threshold, signals are being filtered before reaching the broker.
