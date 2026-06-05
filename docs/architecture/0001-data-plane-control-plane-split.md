# ADR 0001 — Split the LLM off the trading critical path (data plane / control plane)

**Status:** Accepted — incremental migration in progress
**Date:** 2026-06-05

## Context

The platform is event-driven and in-process everywhere except one place: the
**per-signal trading decision**, which makes a synchronous, blocking call to an
external, rate-limited, non-deterministic LLM (`ReasoningAgent._call_llm`). The
liveness of the *entire* system hangs off that one call:

```
signal → BLOCKING LLM call → decision → order → fill → grade → IC → reflection → proposal
                  │
                  └─ if it fails (429 / timeout / budget) → REJECT
```

When the provider is throttled (observed: Groq free tier at ~87% error,
`success_rate 12.5%`), the agent fails closed and **rejects every signal**. No
trades close, so `GradeAgent`, `ICUpdater`, `ReflectionAgent` and
`StrategyProposer` sit idle (`event_count: 0`) — the whole learning half of the
loop starves. The wiring is intact (see the wiring audit); the architecture is
the problem.

Every existing mitigation is a symptom of this single mismatch — a slow,
throttled component on a fast, real-time path:

- reactive backoff/retry on 429s (`llm_router`),
- proactive sliding-window limiter (`_GeminiRateLimiter`),
- demand throttling (`REASONING_COOLDOWN_SECONDS`, `REASONING_DEDUP_PRICE_PCT`),
- the multi-tier provider fallback chain,
- `LLM_FALLBACK_MODE=reject_signal`.

## Decision

**Separate the two jobs the LLM is doing, because they run at different speeds:**

- **Data plane (fast, deterministic, local, always available):** decide buy /
  sell / hold on *this* signal in microseconds, with no external call.
- **Control plane (slow, LLM, off the hot path):** deliberate periodically —
  tune the policy's parameters, evolve the adaptive directive, form hypotheses.

```
DATA PLANE     signal → decide_policy(params) → decision        (µs, no network)
CONTROL PLANE  every N min / on events → LLM → updates params + directive
```

The LLM stops being a per-tick decision-maker and becomes a periodic
**policy updater**. Trades keep flowing when the LLM is degraded, so the learning
loop never starves, and "provider throttled" degrades to "we haven't
re-deliberated lately" instead of "the system is dark." This is already
half-built: the self-evolving directive loop *is* a control-plane deliberation —
the mistake was that the LLM *also* makes every tick decision.

## The deterministic policy

`api/services/decision_policy.py` — pure, no IO, fully unit-tested. Given the same
context the LLM sees (composite score, momentum direction, news sentiment, macro
regime, order-book imbalance) plus a `PolicyParams` set, it returns the same
decision summary shape the LLM path emits, with an **auditable** rationale (every
contributing term is reported in `risk_factors`). Scoring is a transparent
weighted blend of directional features in `[-1, 1]`, threshold-cut and gated by a
minimum confidence.

`PolicyParams` (buy/sell thresholds, feature weights, sizing, stop, RR) is the
control plane's output — an immutable, versionable value, mirroring how the
adaptive directive is stored.

## Migration (incremental, each step shippable and reversible)

1. **[DONE] Build the data-plane decider** (`decision_policy.py`) + wire it as a
   new fallback mode `LLM_FALLBACK_MODE=local_policy`. When the LLM is
   down/throttled/over-budget the deterministic policy decides instead of
   rejecting, so trades keep flowing and the loop keeps turning. Default remains
   `reject_signal` (fail closed) — operators opt in. **This is the first slice.**
2. **[DONE] Promote the policy to primary** behind `DECISION_MODE`
   (`llm` | `policy` | `hybrid`), routed in `ReasoningAgent._produce_decision`:
   - `policy`: the data plane decides every signal; `_call_llm` is never invoked
     on the hot path (`model_used="policy"`).
   - `hybrid`: LLM-primary, but `_degrade` falls to the deterministic policy on
     any LLM failure — never goes dark, regardless of `LLM_FALLBACK_MODE`.
   - `llm` (default, unchanged behavior): the LLM decides AND the policy runs in
     **shadow** (`_shadow_compare_policy` logs `decision_shadow_compare` with
     `agree`), so policy-vs-LLM agreement is measurable before flipping the
     default. Params are read through `get_policy_params()` (the control-plane
     seam). Default stays `llm` — opt in per deployment.
3. **[NEXT] Close the control loop:** extend the directive-evolution machinery so
   the LLM (and the grade/reflection loop) updates `PolicyParams` on the slow
   loop, stored + versioned in Redis like the directive. The challenger system
   already A/B-tests deterministic strategies — the same harness validates param
   sets before promotion.
4. **[LATER] Retire the per-signal LLM call** on the hot path entirely; the LLM
   runs only on the control plane.

## Consequences

- **Liveness no longer depends on an external API.** A throttled/zero-quota
  provider can no longer take the trading + learning pipeline down.
- **Decisions become auditable and deterministic** on the data plane (every term
  is reported), while the LLM keeps the system *adaptive* on the control plane.
- **The rate-limit machinery stops being load-bearing.** Backoff/cooldown/dedup
  become optimizations for the slow control-plane calls, not survival mechanisms
  for the hot path.
- **Trade-off:** the deterministic policy is simpler than full LLM reasoning per
  signal. That is acceptable and by design — the LLM's judgement re-enters as the
  *parameters and directive* it sets on the slow loop, where its latency and
  rate limits don't matter.

## References

- `api/services/decision_policy.py` — the data-plane decider
- `api/services/agents/reasoning_agent.py::_apply_fallback` — `local_policy` wiring
- `api/services/llm_router.py` — the rate-limit machinery being demoted
- Wiring audit (session) — confirms producer→consumer graph is fully connected
