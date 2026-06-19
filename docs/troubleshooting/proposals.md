# Proposals

Strategy-proposal lifecycle: creation (StrategyProposer), creation-time
guardrails (dedup + daily cap), the `/dashboard/learning/proposals` read path,
and the dashboard Proposal Queue (ingestion, approve/reject, empty state).

---

## Auto-proposals #334 / #338 / #339 — implementing the learning-loop's "code_change" issues

**Context:** The learning loop files vague `code_change` / `regime_adjustment`
GitHub issues for "a human to design." Three were actioned together. Each was
implemented as a **bounded, default-neutral** lever (no live behavior change
until an operator/control-plane opts in) rather than a literal reading of the
machine-written text.

- **#334 "signal confidence too low" (regime_adjustment).** Already largely
  resolved by the `HYPOTHESIS_PARAM_MAP` routing fix (PR #337, see the entry
  below). Hardened against recurrence: added near-miss category aliases
  (`low_confidence`, `signal_confidence_too_low`, `execution_threshold_too_low`,
  `decision_threshold_too_low`) so an un-normalized LLM label still auto-routes
  to `PARAMETER_CHANGE` instead of reopening the issue.
  *Regression:* `tests/core/test_param_evolution.py::test_near_miss_confidence_aliases_route_to_gate`,
  `tests/agents/test_strategy_proposer.py::test_near_miss_confidence_alias_routes_to_parameter_change`.

- **#338 "consider buying instead of selling" (code_change).** A literal sell→buy
  inversion would defeat momentum and the risk hierarchy, so it is NOT done.
  Implemented instead as `PolicyParams.directional_bias` (default `0.0`): an
  additive tilt on the deterministic policy's blended score, clamped to
  `[-1, 1]`, surfaced in `risk_factors`. It cannot bypass the confidence floor.
  Control-plane tunable via `set_policy_params`.
  *Regression:* `tests/core/test_decision_policy.py` (`test_positive_directional_bias_tilts_flat_signal_to_buy`,
  `test_directional_bias_cannot_force_a_trade_below_min_confidence`, …).

- **#339 "avoid trading in the morning" (code_change).** Added a configurable
  no-trade time-window gate (`NO_TRADE_WINDOW_ENABLED` / `_START_ET` / `_END_ET`,
  off by default). When on, NEW long entries (BUY) are blocked while the ET wall
  clock is inside `[start, end)`; **exits (SELL) are never gated** so the book
  can always de-risk (same long-only-exit stance as the cooling-off gate). The
  pure window check is `MarketStatusService.is_within_window` (ET, wrap-aware);
  the gate fires in `ExecutionEngine._check_pre_execution_gates`.
  *Regression:* `tests/core/test_market_status.py` (window cases),
  `tests/agents/test_execution_engine_helpers.py` (`test_no_trade_window_*`).

---

## Same "signal confidence too low" proposal re-files a GitHub issue every day (issue #334)

**Symptom:** The learning loop opened a fresh `[auto] regime_adjustment` GitHub
issue for the *identical* generic hypothesis — "The model's signal confidence is
too low, resulting in suboptimal trade execution" (regime `losing`) — on a
recurring basis (issue #324, then #334, …). The earlier code fix (#324, graduated
confidence in `signal_generator`) did not stop the recurrence because the
proposal is produced upstream of the signal generator entirely.

**Root cause:** `StrategyProposer._build_proposal` routed only the exact literal
`type == "parameter"` hypothesis to the auto-applyable `PARAMETER_CHANGE` path.
A `type == "signal_confidence"` hypothesis — which is really a request to tune
`SIGNAL_CONFIDENCE_MIN_GATE`, an allowlisted auto-tunable parameter — fell into
the `else` branch → `REGIME_ADJUSTMENT` → a GitHub issue claiming it "needs
code." Proposal dedup is **date-keyed** (`proposal_guardrails`, resets daily),
so the same hypothesis reopened a brand-new issue every cycle with no path to
ever auto-resolve.

**Fix:** Added `HYPOTHESIS_PARAM_MAP` + `parameter_for_hypothesis()` to
`api/services/param_evolution.py` (the single source of truth for tunables) and
a routing branch in `StrategyProposer._build_proposal`: a hypothesis whose
category maps to a known tunable parameter now routes to `PARAMETER_CHANGE`
(opening a concrete, bounds-valid config PR when the hypothesis carries a value,
else a description-only review item) instead of a recurring `REGIME_ADJUSTMENT`
GitHub issue. Genuinely strategic categories (`regime`, vague `risk_management`)
stay unmapped, so real design proposals still reach a human.

**Regression test:**
`tests/agents/test_strategy_proposer.py::test_signal_confidence_hypothesis_routes_to_parameter_change`,
`tests/core/test_param_evolution.py::test_signal_confidence_hypothesis_maps_to_gate`

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

---

## Approving a challenger promotion did nothing (and 404'd) — the loop didn't close

**Symptom:** A `challenger_promotion` proposal reached the Proposals page, but
clicking **Approve** had no effect on the bot, and for challenger proposals it
often 404'd. Promotions were displayed, then discarded — the "promotions →
advise agent behavior" loop never closed.

**Root cause:** Three gaps. (1) `ProposalApplier` had **no handler** for
`challenger_promotion`, so even when applied it fell through to
`proposal_skipped_unknown_type`. (2) Nothing ever *re-applied* on approval — the
approve endpoint only flipped a `status` field; the applier consumes
`STREAM_PROPOSALS` at publish time and had no `requires_approval` gate, so a
proposal was either auto-applied on first sight or never. (3) Challenger
proposals persist to the **`events`** table, but `update_proposal_status_payload`
only `UPDATE`d **`agent_logs`** by `trace_id` — no match → **404**.

**Fix:**
- **Gate, don't auto-apply:** `APPROVAL_GATED_PROPOSAL_TYPES`
  (`api/constants.py`) lists types the applier leaves *pending* until approved.
  `ProposalApplier.process()` skips them on first publish (`proposal_pending_approval`)
  so nothing auto-promotes.
- **Approval re-emits for application:** `republish_approved_proposal()`
  (`api/services/dashboard/proposals.py`) re-publishes an approved, gated proposal
  to `STREAM_PROPOSALS` with `FieldName.APPROVED=True` (folding the spawn `config`
  into `content`), so the applier acts. Same `trace_id` ⇒ the frontend's stable-id
  dedup upserts the row rather than duplicating it.
- **Events fallback:** `_approve_events_proposal()` (`api/services/dashboard/learning.py`)
  sets status on the events-table row (by id or embedded `trace_id`) when the
  `agent_logs` update misses — closing the 404.
- **Handler does both halves (operator chose "Both"):**
  `ProposalApplier._apply_challenger_promotion()` (1) appends a promotion
  advisory to the **durable adaptive directive** via `PromptStore` — the same
  Redis-backed (no TTL, survives restarts/deploys), versioned, history-capped
  channel `PROMPT_EVOLUTION` uses, already read by the ReasoningAgent and shown
  in the **Prompt Evolution panel** (no new hidden state); and (2) spawns the
  strategy as a live shadow candidate via `ChallengerSpawner` (visible in the
  Challengers panel). The advisory de-dupes, so re-approval is idempotent.

**Why the directive, not a new key:** an earlier draft wrote a separate
`learning:strategy_bias` Redis key, but that state was invisible in the UI and a
second place state could drift. Routing through `PromptStore` keeps a single
durable, auditable, operator-visible source of truth.

**Regression tests:**
`tests/agents/test_proposal_applier.py::test_challenger_promotion_pending_without_approval`,
`::test_challenger_promotion_approved_biases_and_spawns`,
`::test_challenger_promotion_reapproval_is_idempotent`,
`tests/api/test_proposal_approval_republish.py`

## Review queue spammed by evidence-less "parameter change" rows

**Symptom:** The proposal queue filled with near-identical pending
"parameter change" rows — no description, no confidence, no backtest delta
(everything `--`), several sharing one trace_id — each with live
Approve/Reject buttons that changed nothing.

**Root cause (three stacked defects):**
1. The ProposalApplier's audit rows (`write_agent_log(trace, PROPOSAL, ...)`)
   carried no `status` and no `content`. Every proposals read path defaults a
   missing status to `pending` and missing content to `{}` — so each change
   the applier ACTED ON re-appeared in the queue as a fresh evidence-less
   pending proposal.
2. The applier had no idempotency: stream retries / DLQ replays redelivered
   the same proposal and re-ran the handler — duplicating PR artifacts and
   audit rows.
3. `_in_memory_proposals` keyed row identity on the trace_id, which all
   proposals from one reflection share — siblings collapsed to one identity
   and approving one row matched all of them.

**Fix:** Audit rows now stamp `status=ProposalStatus.APPLIED` (new enum
member), `requires_approval=False`, a fresh `msg_id`, and carry the applied
summary as `content` (`api/services/agents/proposal_applier.py`). The applier
dedups on msg_id (bounded LRU; approval republishes with `APPROVED=True` still
pass). `_in_memory_proposals` keys rows on `payload.msg_id` and maps legacy
`applied=True` rows to status `applied`
(`api/services/dashboard/proposals.py`).

**Regression tests:**
`tests/agents/test_proposal_applier.py::test_audit_log_row_is_terminal_not_pending`,
`::test_redelivered_proposal_applies_exactly_once`,
`tests/core/test_memory_dashboard_reads.py::test_memory_proposals_have_unique_ids_and_applied_rows_are_not_pending`

## Parameter-change artifacts could never actually apply (two drifting override mechanisms)

**Symptom:** The learning loop "tuned" parameters and the queue showed applied
parameter changes, but no merged change ever altered runtime behavior on the
in-process auto-PR path.

**Root cause:** Two parallel override mechanisms had drifted. The validated
one (`config/param_overrides.json`, safe-bounds checked by
`param_evolution.validate_param_change`, loaded by `api/constants.py` at
import) is what the GitHub Action edits. The in-process
`GitOpsPublisher.open_parameter_pr` wrote a DIFFERENT artifact
(`config/parameter_overrides/*.json`) consumed by a settings-based loader —
but every allowlisted tunable is a **constant, not a Settings field**, so the
loader skipped each merged artifact as "unknown param". Dead path, unvalidated
on top (`REASONING_COOLDOWN_SECONDS`, off-allowlist, flowed through in tests).

**Fix:** Consolidated on the validated mechanism:
- `GitOpsPublisher.open_parameter_pr` now read-modify-writes
  `config/param_overrides.json` via `apply_param_override` (bounds-validated;
  refused BEFORE any branch/PR exists, so no orphan branches; preserves other
  entries; carries the file sha the contents API requires).
- `ProposalApplier._emit_param_change_artifact` enforces
  `validate_param_change` before emitting anything — an unsafe change produces
  no artifact, no PR, and no "applied" audit row (the `param_evolution`
  docstring contract, previously unwired at this site).
- `LLM_CALL_DELAY_MS` added to `PARAM_BOUNDS` (0–2000ms) so GradeAgent's
  rate-limit tuning is a first-class durable tunable instead of a dead artifact.
- Dead mechanism removed: `api/services/config_overrides.py`, its startup
  call, the `PARAMETER_OVERRIDES_DIR` constant, and its tests.

**Regression tests:**
`tests/api/test_gitops_publisher.py::test_opens_pr_when_configured` (asserts
the committed file IS `config/param_overrides.json` with the applied entry),
`::test_updating_existing_overrides_preserves_other_entries`,
`::test_rejects_off_allowlist_or_out_of_bounds_before_any_network`,
`tests/agents/test_proposal_applier.py::test_unsafe_parameter_change_emits_nothing`,
`::test_llm_call_delay_param_change_is_allowlisted`

## Approved challenger promotion could vanish without a trace

**Symptom:** Operator approves a `challenger_promotion` proposal and then…
nothing: no applied log, no notification, no visible change. Reads as
"promotion is broken" — the exact "promoted but nothing happened" report.

**Root cause:** `_apply_challenger_promotion()` returned `None` whenever
nothing actually changed — no prompt store installed, spawner unavailable,
strategy not registered in `backtest.strategies.STRATEGIES`, or an idempotent
re-approval. `process()` treats `None` as "nothing applied" and writes no
record, so the approval left zero trace.

**Fix:** `api/services/agents/proposal_applier.py` — a well-formed approved
promotion now ALWAYS returns an applied summary whose message states exactly
what happened per half: `directive biased (vN)` / `already biased (idempotent
re-approval)` / `skipped — no prompt store installed`, and `candidate spawned`
/ `spawn skipped — spawner unavailable` / `spawn skipped — strategy 'x' not in
backtest.strategies`. Only a malformed payload (missing strategy) is dropped,
with a warning log. Also: the proposal-creation daily-cap drop is now logged at
**warning** (`proposal_skipped_daily_cap`) — from the cap until midnight UTC
every genuine proposal is swallowed, which previously looked like a quiet loop.

**UI legibility (same change):** Proposals page empty state now lists the three
real proposal sources and their thresholds (challenger ≥25 shadow trades +
beats baseline → approval-gated; reflection hypotheses ≥0.7 confidence, capped
daily; C/D/F grades auto-apply and never queue). Agent Scorecards now states
that "★ Promoted" is **trust-tier promotion of pipeline agents** — a different
thing from **challenger strategy promotion**, killing the word collision that
made operators expect a proposal from a scorecard star.

**Regression tests:**
`tests/agents/test_proposal_applier.py::test_challenger_promotion_approved_always_leaves_a_trace`,
`::test_challenger_promotion_trace_names_unknown_strategy`

## Challenger promotions no longer wait for a manual vote

**Symptom:** Operator: "I shouldn't need to press approve — the loop should
just improve itself." Eligible promotions sat pending forever unless someone
visited the Proposals page and clicked Approve.

**Root cause:** `CHALLENGER_PROMOTION` was in `APPROVAL_GATED_PROPOSAL_TYPES`
with no auto-apply path, so the self-evolving loop had a mandatory human stop.

**Fix:** `CHALLENGER_PROMOTION_AUTO_APPLY` (api/config.py, default **True**) —
an eligible promotion (≥ CHALLENGER_MIN_SHADOW_TRADES closed shadow trades AND
beating the live baseline) now applies on first publish: reasoning directive
biased toward the winner + follow-up shadow spawned, with the applied record
written as always. Safe to automate — neither half places live orders or moves
capital, and both are versioned/reversible. Set the flag to `false` to restore
the manual approval gate.

**Regression tests:**
`tests/agents/test_proposal_applier.py::test_challenger_promotion_auto_applies_by_default`,
`::test_challenger_promotion_pending_without_approval` (gated mode, flag off)

## Prompt Evolution history was a wall of near-identical versions

**Symptom:** Operator: "v1 to v10 is all the same — nothing is there." The
Prompt Evolution panel's history showed ~10 versions whose text differed only
in embedded edge/win-rate numbers, and the ACTIVE directive still contained
the same `Promoted strategy 'mean_reversion': …` line stacked five times
(state written before the replace-not-append fix).

**Root cause:** Every re-promotion of an already-promoted strategy called
`set_directive`, minting a full new version + history entry for a
numbers-only refresh; and nothing healed directives whose Redis state already
held stacked advisory lines — they stayed stacked until the *next* promotion.

**Fix:** (`api/services/prompt_store.py`) `set_directive` now (1) no-ops on
text identical to the active directive, and (2) accepts
`bump_version=False` to refresh the active text in place — same version, no
history entry. `_bias_directive_toward`
(`api/services/agents/proposal_applier.py`) passes `bump_version=False`
whenever the strategy already had an advisory line. `get_directive`
self-heals on read via `dedupe_promotion_advisories()` — stacked
`Promoted strategy 'X':` lines collapse to the newest one per strategy, so
the live LLM prompt and the panel never show the pre-fix wall still stored
in Redis.

**Regression tests:**
`tests/api/test_prompt_store.py::test_identical_text_does_not_burn_a_version`,
`::test_in_place_update_keeps_version_and_history`,
`::test_read_self_heals_stacked_promotion_advisories`,
`tests/agents/test_proposal_applier.py::test_repromotion_refreshes_advisory_without_version_bump`

## Proposals created by GradeAgent / ChallengerAgent never appeared on the UI

**Symptom:** Operator: "proposals not showing on the UI, nothing working — I
don't see any being created, no auto-PRs, no prompt updates." The `proposals`
Redis stream held 31 entries, but the dashboard Proposals queue was empty.

**Root cause:** Two layers.
1. *Primary (operational):* the only LLM provider (`groq`) was failing 100% of
   calls (0 successes ever — missing/invalid `GROQ_API_KEY`), so the LLM-driven
   chain was dead: ReflectionAgent emitted no hypotheses (`reflection_outputs`
   stream empty), so StrategyProposer produced no proposals, no
   `PROMPT_EVOLUTION`, and no `PARAMETER_CHANGE` → no auto-PRs, no prompt
   updates. Fix is a deployment secret, not code.
2. *Code gap:* the proposals that DO get created without the LLM —
   `GradeAgent` tool-governance and `ChallengerAgent` promotions — published to
   `STREAM_PROPOSALS` but never called `persist_proposal()`. The dashboard reads
   the *persisted* store, not the stream, and `ProposalApplier` only persists a
   proposal once it APPLIES it (returning early on an approval-gated pending
   proposal without persisting). So a pending human-approval proposal never
   surfaced. In memory mode the persisted store (`InMemoryStore.event_history`)
   is also wiped on every restart with no rehydration, so even applied proposals
   vanished on redeploy.

**Fix:** `GradeAgent._emit_tool_governance` and
`ChallengerAgent._maybe_propose_shadow_promotion` now call `persist_proposal()` right
after publishing (mirroring StrategyProposer). `persist_proposal()`
(`api/services/agents/db_helpers.py`) mirrors to a durable Redis list
(`proposals:recent`, `RedisStore.push_proposal`/`list_proposals`), and
`api/startup.py::_hydrate_proposals_from_redis()` replays it into the runtime
store on boot — so the queue survives restarts in memory mode. Control-plane
grade reactions (weight reduction / suspension / retirement) are deliberately
NOT persisted at creation: they auto-apply and the applier records them as
applied audit rows, so persisting them as pending would spam the queue with
Approve/Reject buttons for actions already taken.

**Regression tests:**
`tests/api/test_redis_store.py::test_push_proposal_roundtrip_and_defaults`,
`::test_proposals_list_cap_is_enforced`,
`::test_persist_proposal_mirrors_to_redis_in_memory_mode`,
`::test_startup_hydrates_proposals_from_redis`

## The self-improvement loop produced nothing — no proposals, no PRs, no prompt evolution

**Symptom:** Operator: "nothing is creating proposals — no new agents, no
challengers, no auto-PRs or GitHub issues, no prompt updates. The proposals are
bullshit, not helpful links." The `reflection_outputs` stream was empty (0 ever)
while challenger/grade proposals fired normally.

**Root cause:** Three independent things, none of them the LLM key (which works
intermittently — Groq free-tier rate-limits cause periodic `fallback:reject_signal`):
1. **ReflectionAgent never triggered.** `REFLECT_EVERY_N_FILLS` defaulted to 10,
   but this paper system closes only a handful of trades a day (3 total when
   diagnosed), so `self._fills % 10 == 0` was never true → no reflection → no
   hypotheses → `StrategyProposer` never ran. StrategyProposer is the ONLY
   producer of the artifact-creating proposal types
   (`PARAMETER_CHANGE`→PR, `CODE_CHANGE`/`REGIME`/`NEW_AGENT`→issue,
   `PROMPT_EVOLUTION`). So the entire "create artifacts" half of the loop was
   dark, while the non-LLM producers (GradeAgent/ChallengerAgent) kept firing.
2. **No on-demand trigger.** There was no way to force the loop, so at low trade
   volume an operator could not generate a proposal to verify the chain.
3. **The artifact link was never surfaced.** When GitOps DID open a PR/issue,
   `GitOpsPublisher` returned the URL and the applier stored it in the proposal
   payload (`pr_url`), but no read path or the frontend exposed it — the link was
   buried inside a stringified `content` blob, so proposals looked like dead text
   instead of helpful links.

**Fix:**
- `REFLECT_EVERY_N_FILLS` default 10 → 3 (`api/config.py`) so reflection fires at
  realistic paper-trade cadence.
- `ReflectionAgent.trigger_reflection()` + `POST /dashboard/learning/reflect-now`
  (`api/routes/dashboard_v2.py` → `trigger_reflection_payload`) force a reflection
  cycle on demand → hypotheses → proposals → applier → PR/issue/prompt-evolution.
- `get_learning_proposals_payload` and `_in_memory_proposals` now surface `pr_url`
  and the applier `message`; the frontend `Proposal` type carries them and
  `ProposalDetailModal` renders an "Artifact" section with a clickable
  GitHub issue/PR link.

**Still operational, not code:** real PR/issue creation requires `GITHUB_TOKEN`
in the Render env (`GITHUB_REPO` + `GITHUB_AUTOPR_ENABLED` are already defaulted);
without it `GitOpsPublisher` runs dry and the proposal records "GitOps not
configured" instead of a link.

**Regression tests:**
`tests/api/test_learning_routes.py::test_trigger_reflection_runs_live_agent`,
`::test_trigger_reflection_degrades_when_no_agent`

## Proposals page empty / garbled in memory mode (raw event envelopes)

**Symptom:** With no Postgres (the deployment's reality) the Proposals page
showed no usable proposals — rows had no type, no content, and shared/blank
identities, even though proposals were being generated and hydrated from Redis.

**Root cause:** The frontend hydrates `state.proposals` from `/dashboard/state`
and the WebSocket snapshot, both of which (in memory mode) come from
`InMemoryStore.dashboard_fallback_snapshot()`. That method emitted proposals as
the **raw event envelopes** it stores them as — `{log_type, trace_id, payload}` —
so the real fields (`proposal_type`, `content`, `id`, `status`, `confidence`)
stayed nested under `payload`. The frontend reads them at the top level, so they
all came back `undefined`: `id` fell to `Date.now()` (identity-less, duplicating
each poll) and `proposal_type` defaulted to `parameter_change`. The DB path
(`MetricsAggregator.get_raw_snapshot`) flattens proposals; the memory path did not.

**Fix:** Added `InMemoryStore.normalized_proposals()` (+ `_normalize_proposal_event`)
as the single source of truth that flattens envelopes to the DB-path shape.
`dashboard_fallback_snapshot()` now uses it (covering both the REST `/dashboard/state`
and the WebSocket snapshot), and `_in_memory_proposals` (the `/dashboard/proposals`
endpoint) delegates to it so every memory-mode surface agrees
(`api/in_memory_store.py`, `api/services/dashboard/proposals.py`).

**Regression test:** `tests/core/test_memory_dashboard_reads.py::test_dashboard_snapshot_proposals_are_flattened_not_raw_envelopes`, `::test_dashboard_snapshot_and_proposals_endpoint_agree`
