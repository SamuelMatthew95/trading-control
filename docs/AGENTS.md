# Agent Implementation Guide

## Agent architecture overview

All agents follow the same pattern:

1. **Event-driven** — listen on a Redis Stream via XREAD, never polled or called directly.
2. **Trace ID propagation** — extract `trace_id` from incoming events; never generate a new one inside an agent.
3. **Structured logging** — use `log_structured()` with `exc_info=True` on errors.
4. **Idempotency** — check `processed_events` table before acting on a duplicate event.
5. **Heartbeats** — write agent status to Redis and `agent_heartbeats` table every cycle.

## Stream chain

```
market_ticks → signals → decisions → graded_decisions
```

**Never rename these streams.** All agents, tests, and the EventBus depend on these exact names.

## Trace ID rules

- Extract from incoming event payload field `"trace_id"`.
- If missing (only possible at the chain entry point), generate `uuid4()` in the price poller **only**.
- Pass `trace_id` through to every `agent_logs` INSERT, every `agent_runs` row, and every outgoing stream payload.
- **Never** generate a new `trace_id` inside an agent's `process_event` loop.

## Agent startup sequence

Every agent must do these things in order on startup:

1. Load its own UUID from the `agent_pool` table by name.
2. Write `WAITING` status to Redis (`agent:status:{name}`) and `agent_heartbeats`.
3. Log a startup message including the stream name it is listening on.
4. Enter the XREAD loop.

## Persistence routing

The `EventPipeline` selects a route **before** attempting any write, making persistence
behavior deterministic rather than exception-driven.

```
determine_persist_route(stream, event) → PersistRoute.DB | MEMORY | SKIP
```

| Route | When selected | Action |
|-------|--------------|--------|
| `SKIP` | Stream is not handled by the pipeline writers | Return immediately — no write |
| `MEMORY` | DB unavailable (any handled stream), **or** `agent_logs` with a malformed payload even when DB is up | Call `write_event_to_memory()` → dispatches to the correct `InMemoryStore` bucket; logs a `warning` |
| `DB` | DB available and payload is well-formed | Call the matching `SafeWriter` method |

`write_event_to_memory` dispatches each stream to its dedicated store method:

| Stream | InMemoryStore method |
|--------|---------------------|
| `agent_logs` | `add_agent_log()` (normalised via `build_memory_agent_log_row`) |
| `orders` | `add_order()` |
| `agent_grades` | `add_grade()` |
| `learning_events` | `add_vector_memory()` |
| `trade_performance` | `upsert_trade_fill()` |
| everything else | `add_event()` (generic fallback — nothing is dropped) |

**Rule:** Never add a bare `try/except` around a pipeline write to handle missing
fields.  Instead, extend `should_route_agent_log_to_memory` (or add an analogous
helper) and teach `determine_persist_route` to select `MEMORY` or `SKIP` before
the write is attempted.

Module: `api/services/persistence_routing.py`

## Adding a new agent

1. Create `api/services/agents/your_agent.py` using the template below.
2. Add a row to the `agent_pool` seed migration with a hardcoded UUID.
3. Register it in `api/main.py` agent initialization block.
4. Add it to the stream chain table in `docs/architecture.md`.
5. Add tests in `tests/agents/test_your_agent.py` — every agent must have a test file.
6. Update `CHANGELOG.md`.

## New agent template

```python
from __future__ import annotations
import uuid
from typing import Any
from api.observability import log_structured
from api.events.bus import EventBus


class NewAgent:
    """Brief one-line description of what this agent does."""

    def __init__(self, redis_client: EventBus) -> None:
        self.redis = redis_client
        self.agent_id = "NewAgent"  # Must match agent_pool.name

    async def process_event(self, event_data: dict[str, Any]) -> None:
        trace_id = event_data.get("trace_id") or str(uuid.uuid4())

        log_structured(
            "info",
            "agent processing started",
            agent=self.agent_id,
            trace_id=trace_id,
        )

        try:
            result = await self._do_work(event_data, trace_id)

            if result:
                await self.redis.publish("output_stream", {
                    "type": "agent_result",
                    "data": result,
                    "trace_id": trace_id,
                    "agent_id": self.agent_id,
                })

            log_structured(
                "info",
                "agent processing completed",
                agent=self.agent_id,
                trace_id=trace_id,
            )

        except Exception:
            log_structured(
                "error",
                "agent processing failed",
                agent=self.agent_id,
                trace_id=trace_id,
                exc_info=True,
            )
            raise

    async def _do_work(
        self, event_data: dict[str, Any], trace_id: str
    ) -> dict[str, Any]:
        """Override with agent-specific logic."""
        return {"status": "processed", "trace_id": trace_id}
```

## Implemented agents

| Agent | File | Status |
|---|---|---|
| SignalGenerator | `api/services/signal_generator.py` | ✅ Implemented |
| ReasoningAgent | `api/services/agents/reasoning_agent.py` | ✅ Implemented |
| GradeAgent | `api/services/agents/pipeline_agents.py` | ✅ Implemented |
| ICUpdater | `api/services/agents/pipeline_agents.py` | ✅ Implemented |
| ReflectionAgent | `api/services/agents/pipeline_agents.py` | ✅ Implemented |
| StrategyProposer | `api/services/agents/pipeline_agents.py` | ✅ Implemented |
| NotificationAgent | `api/services/agents/pipeline_agents.py` | ✅ Implemented |
| HistoryAgent | — | 🚧 Planned |

## Grade scoring formula

`accuracy×0.35 + ic×0.30 + cost_eff×0.20 + latency×0.15`

Automatic actions based on grade thresholds (A–F) are triggered by GradeAgent after each fill.

## LLM models — which model runs where

All LLM calls route through `api/services/llm_router.py`. The provider is chosen
by `LLM_PROVIDER` (default `gemini`); LM Studio can be the primary local model
via `LLM_PROVIDER=lmstudio`. `active_model_label()` returns the `provider:model`
label used to attribute decisions.

| Call site | File | Prompt | Purpose |
|---|---|---|---|
| ReasoningAgent decision | `reasoning_agent.py:_call_llm` | `ADAPTIVE_TRADING_SYSTEM_PROMPT` | buy/sell/hold decision |
| ReasoningAgent self-critique | `reasoning_agent.py:_self_critique` | `REASONING_CRITIQUE_PROMPT` | skeptical review of high-confidence decisions |
| ReflectionAgent | `pipeline_agents.py:_run_reflection` | `REFLECTION_SYSTEM_PROMPT` / `REFLECTION_IMPROVE_PROMPT` | pattern + mistake analysis |
| StrategyProposer | `pipeline_agents.py:_plan_and_rank` | `STRATEGY_PLANNING_PROMPT` | rank reflection hypotheses |

GradeAgent and ICUpdater are **deterministic** (no LLM) — pure math over outcomes.

| Provider | Model var | Default |
|---|---|---|
| gemini (default) | `GEMINI_MODEL` | `gemini-1.5-flash` |
| groq | `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| anthropic | `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` |
| openai | `OPENAI_MODEL` | `gpt-4o-mini` |
| lmstudio (local) | `LM_STUDIO_MODEL` | `meta-llama-3.1-8b-instruct` |

## Decision provenance — grading with model awareness

Every decision records the model that produced it so the learning loop grades
*decisions*, not just outcomes:

1. `ReasoningAgent` stamps `model_used` (`provider:model`, or `fallback`) and
   its `primary_edge` thesis onto the decision summary (→ `agent_logs`, the
   Redis decision record, and the `decisions` stream).
2. `ExecutionEngine` carries `model_used` + `primary_edge` onto the fill events
   (`FillContext` → `trade_performance` / `trade_completed`).
3. `GradeAgent` (`score_trade`) records both on each `trade_evaluations` row
   (columns added in migration `20260502_decision_provenance`).
4. `GET /learning/trades` returns them and the dashboard's trade-detail modal
   shows the model + thesis behind every graded trade.

Learning thresholds (env): `GRADE_EVERY_N_FILLS`, `GRADE_LOOKBACK_N`,
`GRADE_WEIGHT_*`, `IC_UPDATE_EVERY_N_FILLS`, `IC_LOOKBACK_DAYS`,
`REFLECT_EVERY_N_FILLS`, `REFLECTION_TRADE_THRESHOLD`, `RETIRE_AFTER_N_GRADES`,
`HYPOTHESIS_MIN_CONFIDENCE`.

## Common mistakes

| Mistake | Fix |
|---|---|
| Generating `uuid4()` inside `process_event` | Extract `trace_id` from incoming payload instead |
| Using `id=` keyword in `xgroup_create` | Use positional: `xgroup_create(stream, group, "$", mkstream=True)` |
| Logging `error=str(exc)` | Use `exc_info=True` instead |
| Calling another agent directly | Publish to the agent's input stream instead |
