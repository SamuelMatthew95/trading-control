# Proposals

Strategy-proposal lifecycle: creation (StrategyProposer), creation-time
guardrails (dedup + daily cap), the `/dashboard/learning/proposals` read path,
and the dashboard Proposal Queue (ingestion, approve/reject, empty state).

---

## Proposal queue duplicated rows, showed everything as "pending", and approve/reject 404'd

**Symptom:** On the Proposals page, the same proposal piled up as new rows on
every poll; proposals that had been approved/rejected read back as "pending"
after a refresh; clicking Approve/Reject appeared to do nothing.

**Root cause:** The store's `addProposal` minted a random `id` and forced
`status: "pending"`, discarding the backend's real id and status. Three knock-on
failures: (1) the REST poll deduped on `p.id`, which never matched the random
stored ids, so every 30s poll re-added all proposals; (2) the real status was
thrown away; (3) the approve/reject `PATCH /dashboard/learning/proposals/{id}`
matches on the backend `trace_id`, but the frontend sent the random id, so the
server returned 404 and the vote was silently dropped.

**Fix:** `addProposal` now derives a **stable id** from the backend identifiers
(`id` → `reflection_trace_id` → `trace_id` → generated fallback), upserts in
place (dedup), and honours the backend `status` while never letting a later
"pending" poll clobber an optimistic approve/reject
(`frontend/src/stores/useCodexStore.ts`). The REST poll
(`frontend/src/hooks/useRestPoll.ts`) and WS handler
(`frontend/src/hooks/useGlobalWebSocket.ts`) both pass the backend `id` + `status`
through. Empty `{}` content is normalised to `""` so the label falls back to
`strategy_name`/`proposal_type` instead of rendering `"{}"`.

**Regression test:** `frontend/src/test/store/proposals-dedup.test.ts`

---

## Review queue could flood with duplicate / repeated proposals

**Symptom:** When reflection runs frequently, the StrategyProposer can emit the
same candidate change every cycle and an unbounded number of proposals per day,
swamping the review queue.

**Root cause:** Proposal creation had no creation-time limits — every strong
hypothesis (and every prompt-evolution draft) was published + persisted
unconditionally.

**Fix:** Added `register_proposal_creation()`
(`api/services/agents/proposal_guardrails.py`), called at both StrategyProposer
creation sites (`api/services/agents/pipeline_agents.py`). It rejects a proposal
whose `(proposal_type, content)` fingerprint was already emitted today, and
stops once `settings.MAX_PROPOSALS_PER_DAY` (default 20, `0` disables) is
reached. State is date-keyed Redis (`proposals:count:{date}`,
`proposals:dedup:{date}` with a 48h TTL) so it holds across worker processes,
survives DB-down memory mode (Redis is always up), and resets each day.
Duplicates do **not** consume cap budget; the check **fails open** if Redis is
unreachable so genuine proposals are never silently dropped.

**Regression test:** `tests/core/test_proposal_guardrails.py`

---

## Proposals page is empty even though the pipeline is wired

**Symptom:** The Proposals page persistently shows "No proposals awaiting
review", and the operator suspects the page is broken.

**Root cause:** Not a render bug. Proposals are only produced after the learning
loop completes a cycle — **closed trades → grades → reflection → strong
hypothesis (confidence ≥ `HYPOTHESIS_MIN_CONFIDENCE`, default 0.7) →
StrategyProposer**. ReflectionAgent itself only runs every
`REFLECT_EVERY_N_FILLS` fills and needs ≥3 buffered fills. An idle system with
no closed trades never reaches the first step, and in memory mode anything
generated is wiped on restart (Render cold-starts).

**Fix:** Documentation/expectation only — the empty state now spells out the
prerequisite chain (`frontend/src/components/dashboard/ProposalsSection.tsx`) so
the empty queue reads as "loop hasn't produced one yet", not "UI is broken".
For proposals to persist across restarts the backend must be in DB mode, not
memory mode.

**Regression test:** `frontend/src/test/components/ProposalsSection.test.tsx` (empty-state copy)

---

## Verifying the loop actually produces proposals (and they reach the UI)

**Symptom:** Unsure whether proposals are being generated, whether the
different types are wired, or whether the dashboard will ever "see" them.

**How it flows (verified end-to-end):**
`trade fills + grades → ReflectionAgent → reflection_outputs → StrategyProposer
→ proposals (PARAMETER_CHANGE / CODE_CHANGE / NEW_AGENT / REGIME_ADJUSTMENT /
PROMPT_EVOLUTION) → ProposalApplier` which routes each type — config auto-PR,
GitHub issue, prompt store, tool registry, or Redis control plane. All agents
run inside the single `gunicorn -w 1` web process (started in the FastAPI
lifespan), so the in-process `InMemoryStore` is **shared** — a proposal the
StrategyProposer writes in memory mode is readable by `/dashboard/learning/proposals`.

**Notes:**
- A reflection-born `PARAMETER_CHANGE` is description-only (the hypothesis schema
  is `{description, confidence, type}`), so the applier's auto-PR is a recognised
  no-op — it's a human-review item, not a fabricated value. Auto-PR fires for
  structured param proposals (or operator approval).
- GitHub auto-PR / issue creation needs `GITHUB_TOKEN` in the Render env
  (declared `sync: false` in `render.yaml`; read via `settings.GITHUB_TOKEN`).
  Without it, application is a safe dry-run no-op.
- The dashboard router is mounted at both `/dashboard/*` and `/api/dashboard/*`,
  so the frontend reaches it regardless of `NEXT_PUBLIC_API_URL`.

**Regression tests:** `tests/integration/test_cognition_loop_flow.py`,
`tests/api/test_dashboard_proposals_read.py`

---

## Challenger beat baseline (+PnL) but produced no proposal — "just static"

**Symptom:** The Learning Loop showed challengers with real shadow evidence
(e.g. `mean_reversion` — 317 shadow trades, 66% win, +$2,121, "beats baseline")
yet `RECENT PROPOSALS` stayed empty and nothing was ever promoted. The winning
verdict was displayed and discarded.

**Root cause:** `ChallengerAgent` computed `beats_baseline_shadow` from
tick-driven shadow trades, but the only paths that emitted a proposal —
`_grade()` and `_retire_with_summary()` — are gated on `self._fills`, which only
increments on live `STREAM_TRADE_PERFORMANCE` events. With the live pipeline idle
(no closed trades), `_fills` stays 0, so a challenger never grades, never retires
at `max_fills` (20), and never proposes — no matter how decisively it beats
baseline in shadow. (Separately, `PromotionGate` has no caller at all.)

**Fix:** Added `ChallengerAgent._maybe_propose_shadow_promotion()`, invoked from
the `STREAM_MARKET_EVENTS` path. Once a challenger accumulates
`CHALLENGER_MIN_SHADOW_TRADES` (25) shadow trades AND beats baseline, it publishes
a single (latched) `proposal_type="challenger_promotion"`,
`requires_approval=True` proposal to `STREAM_PROPOSALS` — which the existing
`event_pipeline` → `safe_writer.write_strategy_proposal` path persists into the
learning-loop queue. Decoupled from live fills; a human approves (nothing
auto-promotes).

**Regression test:** `tests/agents/test_challenger_agent.py::test_shadow_winner_emits_promotion_proposal_once`
