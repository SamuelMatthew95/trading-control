# Changelog

## [2026-06-16] — Regime-aware entry gate: reject marginal longs in a bearish regime (issue #328)

### Changed
- **A new long entry must now clear a higher conviction bar to open at all in a bearish (risk-off) regime — marginal longs are REJECTED, not merely shrunk** — issue #326 made a risk-off regime *shrink* a new long to 0.5× size, but the book still **opened** every marginal long into the falling market, and a stream of weak-conviction half-size longs still bleeds in a sustained bearish leg. This was the learning loop's recurring `regime_adjustment` proposal — *"the negative total PnL suggests the strategy may not be effective… reduce position size or adjust strategy"* (issue #328). A new regime-conditional parameter in the single-source-of-truth policy module, `regime_risk.min_confidence(regime, default, *, is_long)`, raises the floor a new long must clear to `RISK_OFF_MIN_CONFIDENCE = 0.35` (vs the `0.20` seed) in a risk-off regime. The deterministic data-plane policy (`decision_policy.decide_policy`) consumes it: a long whose blended score clears `buy_threshold` but whose confidence is below the regime-adjusted floor now HOLDs ("marginal long rejected in a bearish market") instead of opening. This is the entry-side complement to #326's sizing — marginal longs are rejected, strong longs still open (then shrink via the sizing path).
  - **Fail-safe (unchanged invariant):** resolved as `max(default, RISK_OFF_MIN_CONFIDENCE)` so the gate can only ever *raise* the bar — never lower an already-stricter operator/control-plane floor. Shorts (a bearish tape favours them) and every non-risk-off / unknown / missing / malformed regime keep the default floor, so a lost regime read can never loosen the gate.

  (`api/constants.py`, `api/services/regime_risk.py`, `api/services/decision_policy.py`, `docs/troubleshooting/execution-engine.md`, `tests/core/test_regime_risk.py`, `tests/core/test_decision_policy.py`)

## [2026-06-15] — Regime-aware risk posture in a bearish (risk-off) regime (issue #326)

### Changed
- **Risk management is now regime-aware end-to-end — entry size, stops, take-profit, and the daily-loss kill switch all tighten in a bearish (risk-off) regime** — every risk parameter was a single static constant regardless of market conditions, so the book sized up into a falling market and bled the full default stop on every position, even though the system already computed the macro regime (it fed the reasoning prompt but never reached the sizing or risk-exit paths). This was the learning loop's recurring `regime_adjustment` proposal — *"risk management insufficient, significant losses"* in a bearish regime (issue #326). A new single-source-of-truth policy module `api/services/regime_risk.py` resolves every regime-conditional parameter; consumers read the macro regime where they already have it and ask the policy for the effective value:
  - **Entry sizing (ReasoningAgent):** a NEW long entry is scaled by `RISK_OFF_SIZE_MULTIPLIER = 0.5` in a risk-off regime — the book no longer builds large exposure into a falling market (the dominant loss source). Shorts/sells and other regimes are unscaled.
  - **Stop-loss (RiskGuardian):** LONGs cut at the tighter `RISK_OFF_STOP_LOSS_PCT = 3%` (vs 5% default), tagged `stop_loss_risk_off(...)`.
  - **Take-profit (RiskGuardian):** LONGs bank fragile gains at `RISK_OFF_TAKE_PROFIT_PCT = 6%` (vs 10% default) before a bearish leg gives them back, tagged `take_profit_risk_off(...)`.
  - **Daily-loss kill switch (RiskGuardian):** the portfolio limit tightens to `RISK_OFF_DAILY_LOSS_LIMIT_PCT = 1.5%` (vs 2% default) so it trips sooner on a compounding losing day (portfolio regime proxies off the BTC benchmark).
  - **Fail-safe:** the policy only ever *tightens* in an explicit `RISK_OFF` regime and is a no-op otherwise; shorts and non-risk-off/unknown/missing regimes always get the defaults. All regime reads go through the **cache-only** `market_intel.read_cached_macro_regime` helper (no Alpaca fetch on the hot path), so a cold/missing/malformed regime can never *widen* risk — only the explicit risk-off signal narrows it.

  (`api/services/regime_risk.py`, `docs/troubleshooting/execution-engine.md`, `tests/core/test_regime_risk.py`, `tests/agents/test_risk_guardian.py`, `tests/agents/test_reasoning_agent.py::test_kelly_size_shrinks_for_long_entry_in_risk_off`)

## [2026-06-15] — Graduated signal confidence (issue #324)

### Changed
- **Signal confidence now graduates within a tier instead of pinning to a flat floor** — `classify_signal` quantized every signal into three flat tiers (LOW `0.30`, MOMENTUM `0.55`, STRONG `0.80`), so a near-STRONG move at `z = 2.4σ` scored identically to a borderline `z = 1.5σ` one. Confidence carries `0.50` of the weighted execution gate and scales the Kelly size, so this under-scored genuinely strong moves — losing good trades at the gate and sizing every momentum trade as borderline (the learning loop's recurring `regime_adjustment` proposal, issue #324). The `score` now interpolates from the tier floor toward the next tier's floor by how deep the move sits in its band (`_graduate_score`): MOMENTUM ramps `55 → 80`, STRONG ramps `80 → 95` (clamped). Tier boundaries are exact, so **no buy/sell/hold decision changes** — only the confidence magnitude above a boundary rises. LOW keeps its flat `0.30`; position size still rides the hard `MAX_RISK_PER_TRADE_PCT` Kelly cap (`docs/troubleshooting/signal-generation.md`, `tests/core/test_signal_volatility.py::TestGraduatedConfidence`)

## [2026-06-13] — Cognitive dashboard: real cognition, de-mocked API, memory-mode honesty

### Changed
- **Cognitive dashboard now surfaces the real reasoning, not a sim shell** — the page modelled a simulation contract (weighted news/tech/macro/risk signals, counterfactuals, drift) the live system never fills, so it rendered zeros and `--` while discarding the genuine cognition every decision carries. `api/services/cognitive_live.py` now carries each decision's `confidence`, `reasoning_summary`, `llm_succeeded` / `downgrade_reason`, `timestamp`, and the full `tools_used` perception chain (order-book depth, news sentiment, macro regime, correlation, confluence, similar trades). The Command Center and Trace Explorer were rebuilt around this; dead sim panels (weighted Decision Flow, hardcoded-zero counterfactual quality, always-empty Drift) are gone (`docs/troubleshooting/cognitive.md`)
- **The whole `/cognitive/*` API is now LIVE — all demo/seeded data removed** — `/state` and `/events` dropped the `?demo=true` branch; `/config`, `/agents`, `/trace/{id}` no longer serve the seeded `cognitive/demo.py` loop (they read the real pipeline); `POST /cognitive/reseed` (demo-only) was removed. The standalone deterministic engine in `cognitive/` remains a tested library but is no longer wired to any endpoint
- **Cognitive panel modularized** — the 650-line monolith is now one file per tab under `frontend/src/components/dashboard/cognitive/` with shared primitives in `cognitive-ui.tsx`; raw `$`/`%`/glyph literals replaced by `formatUSD` / `formatPercent` / lucide icons and `UI_COPY`

### Fixed
- **Trace outcome rendered a fabricated `+0.00%`** when realized P&L was absent — a missing field coerced to `0` looked like a real break-even. It now renders only when the value is genuinely numeric (`toFiniteNum`), and the live snapshot reports `mean_regret_pct` / `best_action_rate` as `null` (no data) instead of `0.0`

### Added
- **Memory-mode badge** — the snapshot reports `db_available`; when Postgres is down the header badges "Memory mode" so empty grade/outcome panels read as "DB down", not "broken". Decision freshness (`formatTimeAgo`) now shows on the reasoning card and trace rows

## [2026-06-12] — Deep audit: UTC daily-loss window, Open Exposure KPI

### Fixed
- **Daily-loss kill switch timezone divergence** — the DB path summed "today" by the server's local date while the memory path used UTC; on a non-UTC server the two modes tripped on different trade sets near midnight. Both now use the UTC calendar day (`tests/agents/test_risk_guardian.py::test_db_daily_pnl_query_binds_utc_date`)
- **Open Exposure KPI undercounted and mis-signed** (`/dashboard/system`) — exposure read `position.quantity` directly, so memory-mode REST rows (shaped `qty`/`avg_cost`) counted as $0 and the figure depended on which delivery path each position arrived by; `signedUSD` then rendered the magnitude as `+$…` like a profit. New canonical `positionNotional()`/`positionEntryPrice()` helpers count both shapes, mark against the live price stream, and the KPI formats unsigned (`docs/troubleshooting/frontend.md`)

## [2026-06-12] — Cooling-off gate no longer blocks risk exits

### Fixed
- **One losing close pinned every other position open** — the cooling-off gate (revenge-entry throttle) applied to SELLs too, so after a single loss the ExecutionEngine blocked RiskGuardian's take-profit / trailing-stop / stale / further stop-loss closes for the whole cooldown window. SELLs in this long-only book only reduce exposure and now bypass the gate; BUY entries are still throttled (`docs/troubleshooting/execution-engine.md`, `tests/agents/test_execution_engine.py::test_cooling_off_never_blocks_sell_close`)

## [2026-06-12] — RiskGuardian: memory-mode exits, trailing-stop ratchet, stale-position reaper

### Fixed
- **Stop-loss / take-profit / daily-loss never fired in memory mode** — RiskGuardian read positions only from Postgres and daily PnL only from `trade_performance`, so in a no-DB deployment every risk check silently no-opped and losers rode unbounded. It now routes on `is_db_available()`: positions fall back to a scan of the PaperBroker's `paper:positions:{symbol}` Redis keys (the position source of truth in memory mode), and the daily-loss limit + circuit-breaker drawdown fall back to summing today's closes from the `closed_trades:recent` Redis mirror (`docs/troubleshooting/agents.md`)

### Added
- **Trailing-stop profit ratchet** (`api/services/agents/risk_guardian.py`) — peak-PnL high-water mark per position (`risk:peak_pnl:{symbol}`); arms at `TRAILING_STOP_ARM_PCT` (+3%) and closes when PnL gives back more than `TRAILING_STOP_GIVEBACK_FRAC` (40%) of the peak, so an armed winner always banks ≥ 60% of its peak instead of riding back to the −5% hard stop. Basis change (add / re-entry) resets the ratchet; hard SL/TP bounds unchanged
- **Stale-position reaper** — closes positions older than `STALE_POSITION_MAX_AGE_SECONDS` (4h) whose PnL is still inside the `STALE_POSITION_PNL_BAND_PCT` (±1%) dead band, freeing capital from decayed momentum instead of letting chop bleed it into the hard stop. PaperBroker now stamps `opened_at` on positions (preserved across adds/partial closes, reset on flips, cleared when flat)
- All four new knobs registered in `PARAM_BOUNDS` so the GitOps learning loop can tune them within safe bounds
- Tests: `tests/agents/test_risk_guardian.py` (memory-mode scan, ratchet arm/hold/fire/reset, reaper, daily-loss mirror), `tests/agents/test_paper_broker.py` (`opened_at` lifecycle)

## [2026-06-01] — Cognitive brain: decision counterfactuals + drift detection

### Added
- **Decision counterfactuals** (`cognitive/counterfactual.py`) — each closed trade records what BUY/SELL/HOLD would each have returned on the realized move, the best action, and the regret of the one taken; emitted as a `COUNTERFACTUAL` event, surfaced on the trace and as a decision-quality KPI (`mean_regret_pct`, `best_action_rate`)
- **Drift detection** (`cognitive/drift.py`) — `DriftMonitor` watches rolling streams (trade-grade quality, decision regret, direction hit-rate) and emits a typed `DRIFT` alert when the recent window degrades vs the prior window; `CognitiveLoop.detect_drift()` assesses and emits
- New `EventType.COUNTERFACTUAL` / `EventType.DRIFT`; snapshot gains `counterfactuals` + `drift` blocks
- Frontend: Command Center shows a Decision-Quality card (regret / best-action rate) + a Drift card; the Trace Explorer adds a Counterfactual step
- Tests: `tests/core/test_cognitive_intelligence.py`

### Changed
- `CognitiveLoop.close_trade` — emits the counterfactual and feeds the drift monitor; `cognitive/trace.py` surfaces the counterfactual on each trade trace

## [2026-06-01] — Cognitive brain hardening: walk-forward, governance, lineage, retention

### Added
- **Walk-forward validation** — `cognitive/backtest_gate.walk_forward` evaluates a candidate across several sequential market periods; `cognitive/challenger.review` adds a `walk_forward_consistent` check (candidate must beat baseline in ≥60% of folds) so a single-window fluke can't be promoted
- **News is genuinely backtested** — the gate accepts a per-bar sentiment series; `evolve(..., news=...)` threads it through both the in/out split and walk-forward (previously news was constant-0 and a news-weight proposal was inert)
- **Proposal governance** — `cognitive/governance.ProposalGovernor`: per-window quota, exact-duplicate dedup, and a reject cooldown that benches a target (novelty/retirement); new `ProposalStatus.BLOCKED`
- **Per-trade config lineage** — decision/execution/outcome events and the trace stamp `config_version` + `config_proposal_id`; `CognitiveLoop.merge()` records provenance
- **Event-stream retention** — `EventStream(max_events=…)` evicts oldest events with a monotonic `seq`; `dropped`/`emitted` surfaced in `health`
- `tests/core/test_cognitive_hardening.py` — retention, walk-forward, governance, lineage, and a risk-independence stream invariant (no EXECUTION without a RISK_GATE)

### Changed
- `CognitiveLoop.evolve` — governor admission gate before any backtest; threads news + walk-forward; records governor + scorecard outcomes
- `docs/troubleshooting/cognitive.md` — news-inert-in-backtest fix documented

## [2026-06-01] — Cognitive trading brain: deterministic GitOps-evolved loop

### Added
- `cognitive/` — a deterministic, event-stream-driven multi-agent cognitive brain that wires the full closed loop on one `EventStream`: agents → feature aggregation → math-only decision → hard risk gate → execution → attribution + multi-dimensional grading → observations → ProposalAgent → shadow backtest → challenger → GitOps PR
- Five cognitive specialists (News/Technical/Macro/Risk/Reasoning) as advisory-only modules with deterministic default scorers and an injectable LLM seam, discovered via a central `AgentRegistry`
- Deterministic decision engine `score = Σ signalᵢ·weightᵢ → BUY/SELL/HOLD` (no LLM/agent influence; the `risk` feature is a separate hard gate, never part of the score)
- `LearningEngine` that produces **observations only** (never edits config/weights) + `ImportanceTracker` metadata; first-class `ProposalAgent` with a `ProposalType` hierarchy (weight/prompt/tool/backtest/risk/feature) and a `ProposalScorecard` that learns success-rate by type
- Config-parameterized **paired shadow backtest** (`cognitive/backtest_gate.py`) producing `{pnl, sharpe, drawdown, false-positive}` deltas — the judge every proposal must clear; `cognitive/challenger.py` safety validator (sample size / overfit / risk impact / attribution consistency)
- `cognitive/gitops.py` — branch name, full config diff, evidence-rich PR body, bounds-safe config apply; **never auto-merges**
- Multi-dimensional grading (`cognitive/grading.py`) for trades (Direction/Risk/Execution/Timing → overall), agents, proposals, and config versions
- Per-trade `trace.py` ("why did we?") and `health.py` cognitive-wiring health, both pure reads of the stream
- `config/cognitive_config.json` — Git-versioned weights / thresholds / risk limits (data-not-code, bounds-validated)
- Read-only observability API `api/routes/cognitive.py` (`/cognitive/state|events|config|agents|trace/{id}|reseed`) driven entirely by the stream snapshot
- Tests: `tests/core/test_cognitive_*.py`, `tests/integration/test_cognitive_loop.py`, `tests/api/test_cognitive_routes.py`; docs in `cognitive/README.md` and `docs/troubleshooting/cognitive.md`

## [2026-05-23] — Decision provenance: grade trades with model awareness

### Added
- `api/services/llm_router.py` — `active_provider_and_model()` / `active_model_label()`: single source of truth for the `provider:model` label of the active LLM
- `FieldName.MODEL_USED` — payload key for the model that produced a decision
- Alembic migration `20260502_decision_provenance` — adds nullable `model_used`, `primary_edge`, `decision_cost_usd` columns to `trade_evaluations`
- Per-model **net ROI**: each decision's LLM cost (`decision_cost_usd`) travels with the trade; `GET /learning/model-performance` + the dashboard panel show LLM cost and net P&L (P&L − cost) per model
- `docs/AGENTS.md` — "LLM models — which model runs where" + "Decision provenance" sections

### Changed
- `ReasoningAgent` — stamps `model_used` (`provider:model`, or `fallback`) on every decision; flows to `agent_logs`, the Redis decision record, and the `decisions` stream
- `ExecutionEngine` / `fill_publisher` — `FillContext` carries `model_used` + `primary_edge` onto `trade_performance` / `trade_completed` events
- `trade_scorer.score_trade` + `db_helpers.persist_trade_evaluation` — record decision provenance on each `trade_evaluations` row
- `GET /learning/trades` (+ single-trade) — return `model_used` + `primary_edge`
- Frontend `LearningDashboard` — trade-detail modal shows the model + thesis behind each graded trade

## [2026-05-15] — Execution engine modularisation and observability fixes

### Added
- `api/services/execution/position_math.py` — pure PnL / position-delta functions extracted from `ExecutionEngine`; fully testable without mocking
- `api/services/execution/fill_publisher.py` — `FillContext` dataclass + `publish_fill_events()` replacing three near-identical stream-publishing blocks
- `api/services/execution/order_writer.py` — session-agnostic DB write helpers (`insert_pending_order`, `update_order_fill`, `upsert_position_db`, `insert_audit_log`)
- `tests/agents/test_position_math.py` — 35 unit tests covering all pure position-math functions
- `docs/known-issues.md` — living document for active and resolved bugs with mandatory regression-test references

### Changed
- `api/services/execution/execution_engine.py` — reduced from 1262 to ~560 lines; `process()` delegates to `_process_with_db()` / `_process_in_memory()`; backward-compat shims preserved for existing tests
- `api/services/execution/decision_utils.py` — `_as_score()` helper fixes two bugs: `"n/a"` no longer raises `ValueError` to DLQ, and `float(0.0)` is no longer promoted to `0.5`
- `docs/architecture.md` — updated stream chain table (now includes `executions`, `trade_performance`, `trade_lifecycle`, etc.) and repository structure (includes new execution sub-modules)
- `docs/index.md` — added link to `known-issues.md`
- `AGENTS.md` — fixed stale pytest command to use split subsets per CI requirements

### Fixed
- `GET /system/trading-mode` — now returns `UNKNOWN` when Redis is unreachable (was silently returning `TRADING`, which is fail-open)
- `GET /system/status` — stream lag now uses `DEFAULT_GROUP` constant instead of hardcoded `"trading_workers"` (was always showing "Consumer group not found" for healthy streams)
- `GET /system/status`, `GET /system/logs`, `GET /system/metrics` — guard on `is_db_available()` before creating SQLAlchemy sessions (were probing DB in memory mode)

## [2026-04-26] — Legacy frontend cleanup

### Removed
- Deleted the obsolete `frontend/src/legacy-pages` pages-router implementation (`dashboard-legacy`, `performance`, `logs`, `film-room`, and related bootstrap files).
- Removed unused mission-control UI components and health hooks that were only referenced by the deleted legacy pages.
- Removed the unused `HealthResponse`/`BotControlResponse` frontend type module and the stale `Header` component test tied to removed UI.
- Removed the unreferenced `frontend/src/components/obsidian-pro` prototype dashboard component set.
- Removed duplicate/unused frontend utility modules (`frontend/src/components/theme/ThemeToggle.tsx`, `frontend/src/lib/api.ts`, and `frontend/src/lib/fonts.ts`).

### Changed
- Simplified `frontend/tsconfig.json` by dropping the now-unneeded `src/legacy-pages/**/*` exclusion.
- Updated `frontend/vitest.config.ts` coverage includes to replace a deleted legacy `Header` target with a live dashboard runtime component.

## [2026-03-30] — Complete agent pipeline, price poller rewrite, and dashboard overhaul

### Added
- **Price Poller rewrite**: 5 writes per cycle (Redis cache, Redis stream, pub/sub, Postgres prices_snapshot upsert, Postgres system_metrics insert), price change calculation from previous Redis value, asyncio.timeout(8) on Alpaca fetches
- **7 pipeline agents fully implemented**: SignalGenerator, ReasoningAgent, GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent — all with full agent_runs lifecycle, dedup via processed_events, trace_id propagation, Redis + Postgres heartbeats
- **Stream chain**: market_events → signals → decisions → graded_decisions with proper classification logic at each stage
- **3 new dashboard API endpoints**: GET /dashboard/agents/status (agent status from Redis), GET /dashboard/system/metrics (stream lengths + DB counts), GET /dashboard/events/recent (last 10 events)
- **Frontend PipelineHealthBar component**: visual stream flow with arrow visualization (market_events → signals → decisions → graded_decisions)
- **Frontend AgentsSection**: polls /api/dashboard/agents/status every 10s, shows agent status with color-coded dots (ACTIVE=green, STALE=amber, ERROR=red, WAITING=gray)
- **Frontend SystemSection**: replaced WebSocket status with SSE status, shows pipeline metrics via 6 stream cards, recent events table
- Added "market_events", "decisions", "graded_decisions" to EventBus STREAMS tuple

### Fixed
- Signal classification logic: STRONG_MOMENTUM (≥3%), MOMENTUM (≥1.5%), PRICE_UPDATE (else)
- Agent stream chain: agents now listen to correct streams (was wrong stream names before)
- Test mocks for AsyncSessionFactory using proper async context managers
- LLM router test using patch.dict for _PROVIDERS to avoid groq import
- test_no_unknown_ids updated for JSON-structured log output
- All 117 tests passing, 0 failures
- Full CI/CD compliance: ruff check, ruff format, critical error checks all passing

### Architecture
- All agents use shared helper pattern: _ensure_agent_pool_id, dedup check, agent_runs create/complete/fail, agent_logs, heartbeats
- ReasoningAgent consolidated into pipeline_agents.py (single import point)
- Postgres tables created safely via comprehensive SQL script with IF NOT EXISTS guards

## [2026-03-28] — Project documentation and Claude Code setup

### Added
- .claudaignore file to exclude build artifacts and sensitive files
- CHANGELOG.md with current project state and remaining tasks
- CLAUDE.md with complete architecture documentation and coding rules
- .claude/settings.json with permissions for safe automated commands
- docs/AGENTS.md with agent implementation guidelines

### Verified
- All documentation files created and properly formatted
- Claude Code permissions configured to allow development commands while blocking destructive operations

### Remaining
- Real embedding model not wired into REFLECTION_AGENT (zero vector placeholder)
- REASONING_AGENT uses rule-based logic, no LLM yet
- IC_UPDATER not executing paper trades yet
- NOTIFICATION_AGENT not sending Slack/email yet
- verify_deployment.sh not been run against production yet

## [2026-03-28] — Initial architectural overhaul

### Added
- price_poller as standalone Render worker service
- REST endpoint GET /api/v1/prices with Redis cache + Postgres fallback
- SSE endpoint GET /api/v1/prices/stream replacing WebSocket
- GET /api/v1/agents/status endpoint
- Canonical schema tables: strategies, orders, positions, trade_performance,
  events, processed_events, audit_log, schema_write_audit, agent_pool,
  agent_runs, agent_logs, agent_grades, vector_memory, system_metrics
- prices_snapshot and agent_heartbeats tables
- Exactly-once processing via processed_events in all 7 agents
- trace_id propagation through full agent pipeline
- agent_runs and agent_logs writes on every agent execution
- Frontend REST on mount + SSE live updates
- Skeleton loaders replacing "--" placeholders
- CLAUDE.md with full architecture documentation

### Fixed
- Prices showing "--" — was browser-triggered, now background worker
- Agents stuck at WAITING 0 events — stream name mismatches corrected
- idempotency_key using timestamp — changed to trace_id
- seed migration using gen_random_uuid() — changed to hardcoded UUIDs

### Remaining
- Real embedding model not wired into REFLECTION_AGENT (zero vector placeholder)
- REASONING_AGENT uses rule-based logic, no LLM yet
- IC_UPDATER not executing paper trades yet
- NOTIFICATION_AGENT not sending Slack/email yet
- verify_deployment.sh not been run against production yet
