# Frontend Troubleshooting

## Notifications feed looks stale (3-day-old fill pinned at the top)

**Symptom:** The Notifications panel shows old items (e.g. "BUY filled — 3d ago")
above recent signals, so a live system looks frozen. Memory mode claims data is
ephemeral, yet the old notification persists.

**Root cause:** The notifications list is backed by the Redis `notifications:recent`
list, which is durable and survives restarts. The feed rendered the full list
with no age cap, so a stale fill from a previous session stayed at the top.

**Fix:** `frontend/src/components/dashboard/NotificationFeed.tsx` — the feed now
filters to a live window (`NOTIFICATION_LIVE_WINDOW_MS = 1h`); items older than
that are dropped (`isLiveNotification`). The count badge and header time reflect
the live set; an all-stale list shows "No notifications in the last hour". The
full list is still queryable via the REST history.

**Regression test:** `frontend/src/test/components/NotificationFeed.test.tsx` —
"hides notifications older than 1h…" and "shows a live-window empty state…".

## Live Activity shows "Trade graded" / "Reflection" / "Proposal drafted" while the learning loop is idle

**Symptom:** The Agents "Live Activity" feed lists learning-loop outputs (Trade
graded, Reflection, Factors reweighted, Proposal drafted, Proposal applied) for
every learning agent, while the Proposals and Learning pages are empty and the
Cognitive Engine reports `0/0 trades graded`, `0` proposals. The feed
contradicts the detail pages and makes an idle loop look busy.

**Root cause:** Agent-instance spawn/retire transitions are written to
`agent_logs` with `log_type="lifecycle"` (the in-memory writer falls the message
back to the literal `"lifecycle"`). `buildActivityTimeline` mapped any agent_log
to a stage title purely by `agent_name`, so a spawn row for `STRATEGY_PROPOSER`
rendered as "Proposal drafted", `GRADE_AGENT` as "Trade graded", etc. — agent
churn shown as pipeline output. The dedicated backend endpoints all filter by
`log_type` (GRADE / REFLECTION / PROPOSAL), so they correctly showed nothing.

**Fix:** `frontend/src/lib/activity-timeline.ts` — `buildActivityTimeline` now
skips lifecycle logs (`isLifecycleLog`, `log_type === 'lifecycle'`). Only genuine
output logs surface, matching the backend. The same `isLifecycleLog` guard is
applied at the per-agent count source (`DashboardView.tsx` `realAgents` reduce),
so a spawn row no longer inflates an idle agent's "events" (IC / Reflection /
Proposer now read 0, consistent with the Cognitive Engine's Agent Health).

**Regression test:** `frontend/src/test/helpers/activity-timeline.test.ts` —
"skips agent lifecycle logs so spawn churn is not shown as pipeline output";
`frontend/src/test/components/DashboardView.test.tsx` — "does not count agent
lifecycle (spawn) logs as produced events".

## IC Updater displayed as "Indicator Cache Updater"

**Symptom:** The IC Updater agent is labeled "Indicator Cache Updater" across the
dashboard — nonsensical, since no cache is involved.

**Root cause:** `agentDisplayName` hard-coded a wrong expansion. "IC" is the
Information Coefficient (Spearman rank correlation between an alpha factor's
prediction and the realized return) the agent uses to reweight factors.

**Fix:** `frontend/src/constants/agents.ts` — `agentDisplayName(IC_UPDATER)` now
returns "Information Coefficient Updater", with a comment recording the meaning.

**Regression test:** covered by `frontend/src/test/helpers/agent-pipeline.test.ts`
(the IC pipeline stage resolves its label via `agentDisplayName(AGENT_IC_UPDATER)`).

## Session P&L tile loses negative sign

**Symptom:** When session P&L is negative (e.g. -$20.00), the stats tile in the
Trading page shows `$20.00` instead of `-$20.00`. Color still indicates a loss but
the sign is absent.

**Root cause:** The `formatUSD` helper uses `Math.abs` internally so it always
returns a positive string. The stats tile passed the raw value directly without
adding a sign prefix.

**Fix:** `TradingView.tsx` — stats tile value expression now prepends `-` for
negative P&L: `stats.totalPnl < -0.005 ? '-' + formatUSD(totalPnl) : formatUSD(totalPnl)`.
Positive values intentionally omit `+` to stay visually distinct from the `+$x`
format used in trade-row cells (avoids duplicate-text test ambiguity).

**Regression test:** `frontend/src/test/components/TradeFeed.test.tsx` — component
render suite; the unique sign format prevents `getByText(/\+\$x/)` matching both
the tile and the trade row.

## Win-rate shows 0% when server returns empty summary

**Symptom:** When `/dashboard/performance-trends` returns a zero summary
(`win_rate: 0`, `total_trades: 0`) before any trades are graded, the Win Rate tile
shows `0%` even though `tradeFeed` already contains closed fills with computable PnL.

**Root cause:** The fallback condition only checked `win_rate != null`; a genuine
`0` from an empty summary is not null so the fallback computation was skipped.

**Fix:** `TradingView.tsx` — condition now also requires `total_trades > 0`:
`performanceSummary?.win_rate != null && (performanceSummary?.total_trades ?? 0) > 0`.
When both `win_rate` and `total_trades` are 0, the client computes win rate from
the local `tradeFeed` array instead.

**Regression test:** `frontend/src/test/components/TradeFeed.test.tsx` — verify
win rate shows computed value when summary has zero trades.

## In-memory positions show `unrealized_pnl: 0.0` for active shorts

**Symptom:** In memory-fallback mode, open short positions could appear with
`unrealized_pnl: 0.0` (or stale) even when `last_price` and `avg_cost` clearly
imply non-zero P&L.

**Root cause:** Quantity sign conventions were mixed across memory paths.
Some writers persisted short qty as negative while the in-memory paired-PnL
calculator expected strictly positive qty and treated `qty <= 0` as invalid.
That incorrectly marked valid short rows as stale and excluded their unrealized
P&L from summary totals.

**Fix:** `api/in_memory_store.py` now normalizes open-position magnitude with
`abs(qty)` before applying side-aware formulas:

- long: `(last_price - avg_cost) * qty`
- short: `(avg_cost - last_price) * qty`

Rows are marked stale only when price/cost inputs are missing or malformed, not
because short qty is negative.

**Regression tests:**

- `tests/core/test_in_memory_unrealized_pnl.py::test_unrealized_pnl_long_and_short_and_missing_price`
- `tests/core/test_in_memory_unrealized_pnl.py::test_unrealized_pnl_short_with_negative_qty_uses_absolute_position_size`

**Prevention guidance:** Keep unrealized-PnL math centralized in
`InMemoryStore.paired_pnl_payload()` and avoid re-implementing qty-sign logic in
routes/services. Any new writer that mutates memory positions must preserve
`side` and `qty` consistently and include a memory-mode regression test.

## REST hydration overwrites WS orders with wrong `side` value

**Symptom:** Orders hydrated via `GET /dashboard/state` appear with `side: "buy"`
or `side: "sell"` instead of `"long"`/`"short"`, breaking order panel and
equity curve components that compare against the `'long' | 'short'` union.

**Root cause:** The backend `orders` array uses `OrderSide` values (`"buy"`, `"sell"`).
The WS `trade_fill` path in `_handleTradeNotification` already normalizes these to
`"long"`/`"short"`, but `hydrateDashboard` spread REST orders directly without the
same normalization step.

**Fix:** `useCodexStore.ts` `hydrateDashboard` — map each REST order through a
`normSide` helper (`sell`→`short`, `short`→`short`, `buy`→`long`, `long`→`long`)
before merging into the store.

**Regression test:** `frontend/src/test/store/hydrate-dashboard.test.ts` —
`hydrateDashboard — orders side normalization` suite.

## REST hydration drops WS-sourced positions for symbols not in REST top-N

**Symptom:** In memory-fallback mode (or when positions exceed REST page size),
positions that arrived via WS `dashboard_update` events vanish when a REST hydration
fires, because `hydrateDashboard` replaced `positions` wholesale.

**Root cause:** `hydrateDashboard` did a full overwrite: `updates.positions = data.positions`.
Any WS-sourced position for a symbol absent from the REST response was silently discarded.

**Fix:** `useCodexStore.ts` `hydrateDashboard` — merge by symbol. REST positions are
authoritative for symbols they cover; positions for symbols absent from the REST response
are preserved from existing WS state. An empty REST array is treated as "no data" (no-op).

**Regression test:** `frontend/src/test/store/hydrate-dashboard.test.ts` —
`hydrateDashboard — positions merge` suite.

## Dashboard shows "unreachable" error state during transient REST failure when WS is live

**Symptom:** A brief backend hiccup sets `systemFeedError = "Dashboard API unreachable"`.
The error banner persists even though the WebSocket remains healthy and is streaming
live updates. Dashboard status indicator shows `error` instead of the true `Healthy`.

**Root cause:** `useRestPoll.ts` set `systemFeedError` unconditionally on any fetch
exception, including when `wsConnected=true`. It also continued polling `/dashboard/state`
every 30 s after WS connected, risking stale REST values overwriting fresher WS state.

**Fix:** `useRestPoll.ts` — `systemFeedError` is only set when `!wsConnected`. The
REST dashboard/prices interval is not installed when WS is up; a single hydration fetch
runs on WS connect instead.

**Regression test:** No automated test (React hook interval logic); verified by
checking that `POLL_SLOW_MS` branch is unreachable when `wsConnected=true`.

## Notifications tile showed the capped backlog (200) as if it were new activity

**Symptom:** On a freshly opened dashboard the Agents page "Notifications" tile
read `200` even though nothing had just happened and the feed looked idle. The
number never reflected "what's happening now".

**Root cause:** The tile rendered `notifications.length`. The store hydrates the
Redis `notifications:recent` backlog and caps it at 20 (`useCodexStore`, matching
the backend `REDIS_NOTIFICATIONS_MAX`), so the length is the stored-history size,
not recent activity — it pins at the cap on any established session.

**Fix:** `components/dashboard/agents/AgentsDashboard.tsx` now shows
`countRecentNotifications(notifications, 1h)` as the headline ("Notifications · 1h")
with `N stored (max 20)` and the last-activity time as secondary context. The
recent-count + last-activity helpers live in `frontend/src/lib/notification-metrics.ts`.

**Regression test:** `frontend/src/test/helpers/notification-metrics.test.ts` —
`countRecentNotifications` counts only in-window items, not the full backlog.

## RECENT DECISIONS stat line read like a broken total (last-hour next to all-time)

**Symptom:** The Agents page "Recent Decisions" header showed
`Buys: 0  Sells: 0  Holds: 14  Total: 500`. Operators read it as one tally and
reported the count as wrong/corrupt — `0 + 0 + 14` plainly does not equal `500`.

**Root cause:** The breakdown figures and the total come from *different time
windows* but were rendered side by side with no labels. In
`api/services/redis_store.py::decision_stats`, `buys`/`sells`/`holds` count only
decisions newer than `now - 3600` (last hour), while `total` is the length of
the whole `decisions:recent` list (LTRIM-capped at 50). An established session
pins `total` at the 50 cap regardless of recent activity, so the two figures
are unrelated and were never meant to sum.

**Fix:** `components/dashboard/RecentDecisionsPanel.tsx` now labels the windows
explicitly — a `last 1h` tag in front of Buys/Sells/Holds and an `all-time` tag
(plus a hover title noting the 500 cap and that it won't equal
Buys + Sells + Holds) in front of Total. No data/API change; the figures were
already correct, only the presentation was ambiguous.

**Regression test:** `frontend/src/test/components/RecentDecisionsPanel.test.tsx`
— `labels the last-hour breakdown and the all-time total as distinct windows`.

## Scattered `as Record<string, unknown>` casts — fragile dynamic-field reads

**Symptom:** A static UI audit flagged ~13 sites in `TradingView.tsx` reading
dynamic agent-log / position fields via `(x as Record<string, unknown>)?.field`.
Not crashing (optional chaining guarded them), but fragile and repetitive: each
cast skips runtime validation, and a non-object value reaching a deeper
`...?.data?.symbol` access could throw.

**Root cause:** `agentLogs` / `positions` from `useCodexStore()` are typed
narrowly, so every alias field (`confidence_score`, `source`, `data.symbol`,
`decision`, `qty` vs `quantity`, `created_at`) required an inline cast. The
pattern was copy-pasted rather than centralized.

**Fix:** two pure helpers in `src/lib/formatters.ts` —
- `getField(obj, key)`: returns `undefined` unless `obj` is a plain object with
  that key (safe on null/array/primitive),
- `getStr(obj, ...keys)`: first present alias coalesced to a string, else `''`.

All 13 casts in `TradingView.tsx` replaced with these. One canonical, tested
accessor instead of scattered unchecked casts. `LearningLoopPanel.fmtUSD` also
hardened to render `--` for null/NaN, and `AgentStatusTable` empty-row `colSpan`
now uses `COLUMNS.length` instead of a hardcoded `5`.

**Regression test:** `frontend/src/test/helpers/formatters.test.ts` —
`getField` / `getStr` describe blocks (null/array/primitive safety, alias
coalescing, stringification).

## Rule-based fallback decisions were indistinguishable from real model reasoning

**Symptom:** When the LLM is unavailable (deployment/config), the ReasoningAgent
emits `fallback:skip_reasoning` decisions with `llm_succeeded: false`, but the
"Recent Decisions" panel rendered them identically to model-reasoned calls — a
confident-looking `BUY SOL 55%` with nothing marking it as a rule-based
fallback. The whole feed looked like normal (if random) AI decisions, so the
operator couldn't tell the system was running degraded.

**Root cause:** `RecentDecisionsPanel.tsx` only rendered action/symbol/price/
confidence and ignored the `llm_succeeded` / `reasoning_summary` fields the
`/decisions` endpoint already returns. (Only `TradingView.tsx` had fallback
labeling, via its local `resolveMessage`, and it covers the Agent Activity feed,
not this panel.)

**Fix:** `components/dashboard/RecentDecisionsPanel.tsx` adds
`isFallbackDecision(d)` (`llm_succeeded === false` or a `fallback:`-prefixed
`reasoning_summary`). Fallback rows get an amber `rule-based` tag, and the
header shows an `N/M rule-based` summary with a tooltip ("LLM unavailable —
rule-based fallback decisions, not model reasoning"). Amber (caution), not red
(error): the data is intentional degradation, not a crash. No API change.

**Regression test:** `frontend/src/test/components/RecentDecisionsPanel.test.tsx`
— `flags rule-based fallback decisions so they are not read as model reasoning`
and `shows no fallback markers when every decision used the LLM`.

## Live Reasoning panel showed a green "live" pulse while the LLM was down

**Symptom:** On the Agents page, the "Live Reasoning" cockpit always showed a
pulsing green `live` indicator as long as `/dashboard/prompt-os` returned — even
when the LLM provider was at a 100% error rate (`fallback_mode: true`) and every
decision was a rule-based fallback. The cockpit looked healthy while the AI
wasn't actually reasoning.

**Root cause:** The header dot only reflected whether the prompt-os *config*
fetch succeeded; it had no knowledge of LLM call health. `/llm/health` already
computes a canonical `status` (`live`/`degraded`/`down`/`unknown`) but the panel
never consulted it.

**Fix:** `components/dashboard/LiveReasoningPanel.tsx` now also fetches
`/llm/health` (best-effort — a failure leaves the prior status, never blanks the
panel) and drives the indicator from `status`: green pulse only when `live`,
amber when `degraded`, red `LLM down · fallback` when `down`, neutral when
`unknown`. When degraded/down it shows an amber banner stating decisions are
currently rule-based fallbacks and that the prompt/tools below are still the
configured strategy. No pipeline/behavior change.

**Regression test:** `frontend/src/test/components/LiveReasoningPanel.test.tsx`
— `surfaces an LLM-down indicator and fallback banner when the provider is unhealthy`.

## Open Positions table showed P&L 0.00 for every position (stale stored value)

**Symptom:** In memory mode the Trading page's Open Positions table showed
`+$0.00` P&L for every open position, even when `last_price` clearly differed
from `entry_price` — while the equity curve / Session P&L showed a non-zero
unrealized figure. The two disagreed, so the table looked broken.

**Root cause:** Three position read paths existed and only one marked to market.
`paired_pnl_payload()` (equity curve / summary) computed unrealized PnL from
avg_cost vs last_price, but `_normalize_position()` (the `/dashboard/state`
snapshot the table renders) and `open_positions()` (MCP `get_positions`)
returned the raw stored `unrealized_pnl` — written once at fill time (0.0 when
last == entry) and never updated as price moves.

**Fix:** Extracted the formula into one shared
`InMemoryStore._position_unrealized_pnl()` (abs(qty), side-aware) and used it in
all three paths (`_normalize_position`, `open_positions`, `paired_pnl_payload`),
falling back to the stored value (or flagging stale) only when avg_cost/last_price
are missing. Every position read path now marks to market and agrees. (The stored
`last_price` itself can still lag the latest tick — a shared limitation the equity
curve has too — so the table is now *consistent* with the rest of the system.)

**Regression test:** `tests/core/test_in_memory_unrealized_pnl.py::test_open_positions_marked_to_market_not_stale_stored_value`

## Open Positions P&L stayed flat as the market moved (frozen fill price) + missing P&L %

**Symptom:** After the stale-stored-value fix, in-memory Open Positions still
didn't track the live market — P&L matched the price at the last fill, not the
current ticker (e.g. SOL sat at 0.00 because last == entry) — and the P&L %
column always showed "--".

**Root cause:** In memory mode nothing updates a position's `last_price` as
prices move (it's frozen at fill time), and the rows never carried `pnl_percent`.

**Fix:** (1) `InMemoryStore.apply_current_prices(prices)` marks stored positions
to the latest prices; `get_state_payload` (`/dashboard/state`) calls it in memory
mode with the Redis price cache it already fetches, then rebuilds the positions
via `normalized_open_positions()` — so the table, Session P&L, and MCP
`get_positions` all read the same live-marked figures from the shared store.
(2) `_position_pnl_percent()` now populates `pnl_percent` (return on cost basis)
on every position read path, so the table's P&L % column renders.

**Regression test:** `tests/core/test_in_memory_unrealized_pnl.py::test_apply_current_prices_marks_positions_to_live_price`

## Agents dashboard shows healthy agents as "Stale" / agents missing

**Symptom:** On `/dashboard/agents` the Agent Status table painted live agents
as "Stale" (and the pipeline read "0 of 8 live") even though the Agent
Instances table right next to it showed the same agents as "active" — the two
tables contradicted each other and the whole page looked disconnected. Agents
that had not reported yet were absent entirely.

**Root cause:** `DashboardView.tsx` used a 10s "Live" window
(`AGENT_LIVE_THRESHOLD_MS = 10_000`). Agents heartbeat every 15–60s, so a
healthy agent almost always fell outside the 10s window and rendered "Stale".
This contradicts the backend contract (`api/constants.py`:
`AGENT_STALE_THRESHOLD_SECONDS = 120`, `AGENT_HEARTBEAT_TTL_SECONDS = 300`).
The agent list was also built only from agents that had reported, so a
never-seen agent silently vanished instead of showing as Idle.

**Fix:** `DashboardView.tsx` — `AGENT_LIVE_THRESHOLD_MS` → `120_000` and
`AGENT_STALE_THRESHOLD_MS` → `300_000` to mirror the backend heartbeat
contract; removed the now-redundant Reasoning 90s override. The `realAgents`
rollup backfills the full `ALL_AGENT_NAMES` roster as Idle so every documented
agent is always represented. Agents section widened to `max-w-screen-2xl`.

**Regression test:** `frontend/src/test/components/DashboardView.test.tsx` —
`keeps an agent Live while its heartbeat is within the backend 2-min window`
and `always registers the full agent roster, even before any agent reports`.

## Light mode is broken / "weird" after the operator-console redesign

**Symptom:** Toggling the header Sun/Moon into light mode produced a broken,
half-dark UI — dark `slate-950` panels floating on a light page, invisible
`text-slate-100` values, and legacy widgets rendering in light while the
redesigned ones stayed dark. Dark mode was fine; light mode looked "weird".

**Root cause:** The dashboard redesign (PRs #280/#281) hardcoded dark-only
Tailwind classes and dropped the `dark:`/light variants — e.g.
`dashboard-styles.ts` `cardClass` went `border-slate-300 bg-white … dark:bg-slate-900`
→ `bg-slate-950/80` (dark only), `valueClass` `text-slate-950 dark:text-slate-100`
→ `text-slate-100`, and `layout.tsx`/`SystemDashboard.tsx`/`CognitiveDashboard.tsx`
lost every light counterpart. The app still ships `next-themes` (class strategy,
full light palette in `globals.css`) and a Sun/Moon toggle, so light mode was
reachable but no longer styled.

**Fix:** Restored light↔`dark:` duality across the redesigned surfaces, keeping
the redesign's dark "console" tone as the `dark:` variant: light base is the
bare utility (`bg-white`, `border-slate-200`, `text-slate-900`, muted
`text-slate-500`), dark is `dark:…`. Centralized the panel/label/value classes
in `lib/dashboard-styles.ts` (`cardClass`, `consolePanelClass`,
`consoleHeaderClass`, `sectionTitleClass`, `mutedClass`, `valueClass`) and routed
`SystemDashboard.tsx` / `CognitiveDashboard.tsx` through them so all pages stay
consistent. `text-white` on the emerald logo and the mobile scrim stay
theme-agnostic by design.

**Regression test:** Covered by the existing
`frontend/src/test/components/system/SystemDashboard.test.tsx` and
`DashboardView.test.tsx` render suites; the full `vitest` + `next build` + `tsc`
+ `next lint` gate plus a dark-only-leak grep (`bg-slate-9xx` / `text-white` /
`text-slate-100` without a `dark:` sibling on the line, which returns empty)
guard against regressions.

## Light mode still "weird" on every page — shared `DashboardView` frame stayed dark

**Symptom:** Even after the dual-theme sweep above, light mode looked broken on
*every* dashboard page (Overview, Trading, Agents, Learning, Proposals, System):
the whole content area sat on a dark `slate-950` background with light cards
floating on it, and the top "Runtime agents / Agent health…" header rendered as
a dark panel with white text while the sidebar, header bar, badges, and banner
were correctly light.

**Root cause:** The earlier sweep fixed the section *body* components and the
shared style helpers in `lib/dashboard-styles.ts`, but missed the section
*frame* that `DashboardView.tsx` renders around every section: the root wrapper
`<div className="min-h-screen bg-slate-950 … text-slate-100">` and the
`SectionHeader` (`bg-slate-950/90`, `border-slate-800/80`, `text-white`,
`text-slate-500`). Those are dark-only with no `dark:`/light variants, so they
ignored `next-themes` and stayed dark in light mode. Because the frame is shared
by all six sections, the bug reappeared on every page at once.

**Fix:** Restored light↔`dark:` duality on both shared spots in
`app/dashboard/DashboardView.tsx`, matching the layout/`consolePanelClass`
conventions — root wrapper is `bg-slate-100 text-slate-900 dark:bg-slate-950
dark:text-slate-100` (same base as `layout.tsx`), and `SectionHeader` is
`bg-white border-slate-200 … text-slate-900` with the console dark tone moved
behind `dark:` (`dark:bg-slate-950/90`, `dark:border-slate-800/80`,
`dark:text-white`). The `<pre>` prompt block, emerald logo, mobile scrim, and
inverted active tab stay theme-agnostic by design.

**Regression test:**
`frontend/src/test/components/DashboardView.test.tsx::DashboardView — theming (light/dark duality)`
renders the agents section and asserts the root wrapper and section header carry
light base tokens (`bg-slate-100`/`bg-white`, `text-slate-900`) with no bare
dark `bg-slate-8xx/9xx`, and that the dark tone is only present behind `dark:`.

## System page: Daily PnL, agent activity, and dashboard-API outage were misreported

**Symptom:** On `/dashboard/system` (a) "Daily PnL" summed every order in the
recent-orders window (latest 50, no date boundary), so it included prior-session
PnL; (b) the Agent Activity panel hardcoded `news`/`macro`/`proposal`/`risk`
labels that match no real agent, so the 10 canonical agents showed as
"Waiting"/"No output"; (c) a `/dashboard/state` failure (`systemFeedError` /
`apiHealth.dashboardState='error'`) was never surfaced — the page showed only
generic/stale status. (Raised as P2 Codex review comments on PR #280.)

**Root cause:** `SystemDashboard.tsx` summed `props.orders` unfiltered for Daily
PnL; the Agent Activity rows came from a hardcoded `OPERATOR_AGENTS` list instead
of the canonical `ALL_AGENT_NAMES`; and the health panel read neither
`systemFeedError` nor `apiHealth.dashboardState`.

**Fix:** `SystemDashboard.tsx` — Daily PnL now filters orders to the current UTC
trading day via `startOfUtcDayMs(Date.now())`; Agent Activity derives one row per
canonical agent (plus any extra live agent) matched by `canonicalAgentKey` with
`agentDisplayName` labels, and shows a real "Last seen" age instead of
mislabelling `seconds_ago` as `ms`; added a "Dashboard API" health indicator and
a top-of-view error banner driven by `systemFeedError` /
`apiHealth.dashboardState` so an outage is explicit.

**Regression test:** `frontend/src/test/components/system/SystemDashboard.test.tsx`
(renders all Command Center sections, six headline metrics incl. Daily PnL,
compact health indicators, and decision-feed entries on the empty + populated
states).

---

## Command Center card on /dashboard/system stretched to a half-empty panel

**Symptom:** On the System page, the top-left "Command Center" card (the KPI
strip: Net PnL / Daily PnL / Open Exposure / …) showed a large empty band of
card below its single row of metrics — the table looked stranded at the top.

**Root cause:** The card sits in a two-column CSS grid
(`xl:grid-cols-[minmax(0,1fr)_360px]`) next to the taller Operator controls
panel. Grid items default to `align-items: stretch`, so the short KPI card was
stretched to match the controls panel's height, leaving its content pinned to
the top with empty card beneath.

**Fix:** Added `self-start` to the Command Center card in
`SystemDashboard.tsx` so it sizes to its own content (the KPI row) instead of
stretching to the neighbouring panel.

**Regression test:** `frontend/src/test/components/system/SystemDashboard.test.tsx`
(`sizes the Command Center card to its metrics instead of stretching it`)

## Challenger-promotion proposals rendered as "[object Object]" in the queue

**Symptom:** When a shadow challenger beat its baseline and emitted a
`challenger_promotion` proposal, the Proposal Queue's "Candidate Change" cell
showed the literal text `[object Object]` instead of the human-readable reason,
and the "On Approve" column fell through to the grey generic `Review` badge.

**Root cause:** Two ingestion paths coerced the proposal `content` with
`String(content)`: the live WS path (`useGlobalWebSocket.ts::_handleProposal`)
and REST hydration (`useCodexStore.ts`). Challenger promotions carry `content`
as a structured object (`{ strategy, shadow_edge, confidence, reason }`), so
`String(obj)` produced `"[object Object]"`. The `challenger_promotion` type was
also absent from the `ProposalType` union and from `proposal-routing.ts`, so it
had no routing badge.

**Fix:** New `frontend/src/lib/proposal-content.ts` — `coerceProposalContent()`
prefers an object's `reason`, then a `strategy` summary, then a JSON dump (never
`[object Object]`), and `proposalStrategyName()` extracts the strategy. Both
ingestion paths now route `content` through it (and backfill `strategy_name`).
Added `'challenger_promotion'` to the `ProposalType` union and a routing entry
(`Promote challenger`, new `review` kind — operator action, nothing
auto-applies; indigo badge in `ProposalsSection.tsx`).

**Regression test:** `frontend/src/test/lib/proposal-content.test.ts`
(`extracts reason from a structured challenger-promotion content object`,
`JSON-dumps … (never [object Object])`) and
`frontend/src/test/helpers/proposal-routing.test.ts`
(`routes challenger_promotion to operator review`).

## Reasoning-LLM degraded/down was not surfaced at the page level

**Symptom:** When the reasoning LLM degraded or went down, the only signal was a
small status dot inside the LLM Health panel (Overview) far down the page. An
operator scanning any other section (Trading, Agents, Proposals…) had no
indication the agent had dropped to fail-closed fallback, where new signals are
rejected rather than traded.

**Root cause:** No page-level indicator consumed `/llm/health`'s canonical
`status` (`live`/`degraded`/`down`/`unknown`); the status lived only in
`LLMHealthPanel`, whose poll + status union were declared locally and not
reusable.

**Fix:** Extracted the status vocabulary, types, and poll into a shared
`frontend/src/lib/llm-health.ts` (`LLMStatus`, `LLMHealthData`, `useLlmHealth()`)
— single source of truth per the design rules — and refactored `LLMHealthPanel`
onto it. New `LLMDegradedBanner` (page-level, mounted in `DashboardView` beside
the memory-mode banner) renders an amber `warn` banner when `degraded` and a red
`err` "fallback mode" banner when `down`, noting whether cloud fallback is
enabled; hidden while `live`/`unknown` so it never nags.

**Regression test:** `frontend/src/test/components/LLMDegradedBanner.test.tsx`
(warning when degraded, error/fallback when down, hidden when live/unknown/no
data, notes cloud fallback when enabled).

## Overview shows "Active Positions: N" with no positions list anywhere on the page

**Symptom:** The Overview ("main page") headline read `Active Positions: 1`, but
the operator could not find that position anywhere on the page — the count had no
backing detail. The Open Positions table only existed on the Trading page.

**Root cause:** `DashboardView.tsx`'s overview rendered the four KPI tiles
(including Active Positions), Performance, Equity Curve, Agent Matrix, and Live
Market Prices — but no positions table. `OpenPositionsPanel` was defined *inside*
`TradingView.tsx` and only used there, so the count's detail lived on a different
page. The overview count also used `quantity` only while the table used
`quantity ?? qty`, so the two definitions of "active" could drift.

**Fix:** Extracted `OpenPositionsPanel` into its own reusable component
(`components/dashboard/OpenPositionsPanel.tsx`) and rendered it on the overview
directly beneath the KPI tiles, so "Active Positions" now has visible backing.
The panel filters to genuinely open rows (non-zero qty) and the badge reports
that active count. Added shared `positionQty` / `isActivePosition` helpers in
`lib/formatters.ts` and routed the overview KPI, the Trading stats tile, and the
table through them, so the count and the list can never disagree about which
positions are open.

**Regression test:** `frontend/src/test/components/DashboardView.test.tsx` —
`surfaces the open position on the overview so the Active Positions count has
visible detail` and `excludes flat (qty 0) positions from the overview Open
Positions table`.

## P&L looked static (didn't move with the market) and headline numbers contradicted each other

**Symptom:** Operators reported the P&L "doesn't update, just static" and that the
numbers were confusing "bullshit": the header chip showed e.g. `Total P&L -$0.61`
while the overview headline showed `Daily P&L --` and the Performance card showed
`Total P&L -$0.09` — three different figures, none of them moving as prices ticked.

**Root cause:** Two separate problems.
1. **No client-side mark-to-market.** When prices streamed in over WebSocket, open
   positions' `pnl` was *not* recomputed — it stayed frozen at whatever the backend
   last pushed (only on a fill). So unrealized P&L (and therefore the header "Total
   P&L", which includes it) only moved on fills, never as the market moved.
2. **Three different definitions wearing overlapping labels.** Header "Total P&L" =
   realized(orders) + unrealized(positions). Overview "Daily P&L" = realized(orders)
   only, no date filter (so not actually daily). Performance "Total P&L" =
   closed-trade / DB aggregate (realized). They measured different things but read
   like they should agree.

**Fix:**
- Added mark-to-market helpers in `lib/formatters.ts` (`positionLivePnl`,
  `positionLivePnlPct`, `livePriceFor`, `pricesFreshnessMs`) that value a position
  against the freshest streamed price (side-aware), plus `useLivePositions`
  (re-marks `pnl`/`current_price`/`pnl_percent` every tick) and `useLivePnl`
  (`{realized, unrealized, total}`) as the single P&L source.
- The header chip and the overview headline now both render `useLivePnl().total`,
  so they can never disagree; the overview tile is relabelled **Total P&L** (was the
  mislabelled "Daily P&L") with a `Realized … · Unrealized …` breakdown, and the
  Performance card's cell is relabelled **Realized P&L** to stop it contradicting.
- The Open Positions table (overview + trading) and the System page's P&L Clarity /
  exposure consume live-marked positions, so they move with the market.
- New `LiveNumber` flashes green/red when a value changes and `LiveDot` shows a
  pulsing live indicator, so updates are *visible* instead of silently swapping.

**Regression test:** `frontend/src/test/helpers/live-pnl.test.ts` (mark-to-market
math, `markPositionsToMarket`, `computeLivePnl`),
`frontend/src/test/components/LiveNumber.test.tsx` (flash on change), and
`frontend/src/test/components/DashboardView.test.tsx` —
`shows a live Total P&L = realized orders + mark-to-market unrealized`.

## Trading page "Session P&L" frozen while header "Total P&L" ticked

**Symptom:** On the Trading page the header chip "Total P&L" moved with the market
but the "Session P&L" stat tile right below it sat frozen, only changing every ~30s
(or never). The two contradicted each other on the same page, and every per-page
P&L looked "static" while BTC visibly ticked.

**Root cause:** `TradingView` computed Session P&L from `pnlSummary` — the REST
`/pnl` snapshot refreshed only every `POLL_SLOW_MS` (30s) — and its `stats` `useMemo`
did not depend on `prices`. So it never re-marked open positions to the live price
stream, unlike the header chip and Overview headline which both use `useLivePnl()`.

**Fix:** `TradingView.tsx` now derives Session P&L from `useLivePnl()` (realized +
live mark-to-market unrealized) and active-position count from `useLivePositions()`,
the same canonical source as the header/Overview. The static `pnlSummary` snapshot is
kept only as a fallback when there is no live order/position to mark. The
realized/unrealized sub-line prefers the live split too.

**Regression test:** `frontend/src/test/components/TradingView.test.tsx` —
`values open positions against the live price stream, not the stale snapshot`.

## Every mark-to-market number freezes when the WS tick stream goes silent

**Symptom:** All live P&L (header, Overview, Open Positions) froze together even
though the WebSocket reported "connected" — prices simply stopped updating.

**Root cause:** While `wsConnected` is true, `useRestPoll` deliberately stopped REST
price polling and relied entirely on the WS `market_ticks` stream to update `prices`.
If that stream stalled (poller down / not forwarded) but the socket stayed open,
`prices` froze after the initial mount fetch, and every value derived from it froze
with it. There was no fallback.

**Fix:** `useRestPoll.ts` adds a price-staleness watchdog (only while WS-connected):
every `PRICE_WATCHDOG_MS` (8s) it checks `pricesFreshnessMs(store.prices)` and
re-fetches prices over REST only when the freshest price is older than
`PRICE_STALE_REFETCH_MS` (20s). Live ticks are never clobbered during normal
operation; a silent stream can no longer freeze the dashboard.

**Regression test:** covered indirectly by `frontend/src/test/helpers/live-pnl.test.ts`
(`pricesFreshnessMs` staleness math, which gates the watchdog).

## Daily Change % read 0.00% while the account was underwater

**Symptom:** The Overview "Daily Change %" tile showed `0.00%` even though Total
P&L was negative (e.g. -$0.64) and an open position was clearly down — the two
KPIs, side by side, contradicted each other and the tile never moved.

**Root cause:** Daily Change was computed from realized order PnL only
(`dailyPnlNumeric = Σ order.pnl`) over the equity base. With an open position and
no closed trades the numerator was 0, so it pinned to 0.00% and never moved with
the market — unlike the Total P&L headline, which includes unrealized.

**Fix:** `DashboardView.tsx` — Daily Change now uses the live total P&L
(`useLivePnl().total`, realized + mark-to-market unrealized) over the equity base
(`portfolio_value`/`account_equity`/`equity`/`starting_equity` metric, else the
`DEFAULT_PAPER_EQUITY` $100k fallback mirroring the backend paper capital). The
`summary` memo now depends on `livePnl`, so it recomputes every tick; the backend
realized-only `daily_change_pct` is used only as a no-live-data fallback.
`formatDailyChange` dead-bands `|x| < 0.005%` to a clean `0.00%` (no `-0.00%`
artifact) and the trend arrow uses the same dead-band. This is an account-level
return: a single small position on a $100k paper account is correctly a small %
(the position's own return shows in the Open Positions "P&L %" column).

**Regression test:** `frontend/src/test/components/DashboardView.test.tsx` —
`Daily Change % reflects live unrealized P&L, not realized-only (no longer frozen at 0.00%)`.

## Clicking an agent did nothing — no per-agent grade, learnings, or drill-in

**Symptom:** The Agents view showed only heartbeat liveness (status / event count
/ last seen). There was no way to click into an agent to see what it actually
did, agents had no individual grade or learnings, and "doing well" had no visible
standing — only one system-wide grade existed for the whole trading loop.

**Root cause:** GradeAgent emits a single aggregate grade; nothing graded each
agent on its own telemetry, and the frontend had no detail view to drill into.

**Fix:** New `api/services/dashboard/agent_performance.py` grades every agent on
its OWN telemetry — liveness (heartbeat), success rate (runs completed/failed),
throughput (recent events), and latency (when the DB records it) — reweighted
over whichever dimensions have data, so memory-mode agents are still graded and a
dormant agent is `UNRATED` (not falsely `F`). Letter grade → promotion tier
(`GRADE_TO_TIER`); sustained A/A+ earns a ★ Promoted standing. Exposed via
`GET /dashboard/agents/performance` and `GET /dashboard/agents/{name}/detail`.
Frontend: `AgentScorecards` panel (clickable cards) + `AgentDetailModal` drill-in
showing the grade breakdown, deterministic learnings, heartbeat, and recent
activity (what the agent did).

**Regression test:** `tests/api/test_agent_performance.py` +
`frontend/src/test/components/AgentScorecards.test.tsx`.

## Tool Governance table "didn't make sense" before any trades closed

**Symptom:** With no closed trades, every Tool Governance row read `unused` and
`α … prior`, with no explanation — the table looked broken rather than simply
un-exercised.

**Root cause:** Tool alpha is attributed from realized PnL once trades close; in a
fresh / memory-mode runtime there is nothing to attribute yet, so all rows show
seeded priors. The panel never said so explicitly.

**Fix:** `ToolGovernancePanel.tsx` — when `exercisedCount === 0` the panel now
renders an explicit callout explaining that every row is a seeded prior (α values
are starting estimates, `unused` means the live loop has not exercised the tool)
and that scores go live once trades close and the GradeAgent attributes PnL.

**Regression test:** `frontend/src/test/components/ToolGovernancePanel.test.tsx`
(existing exercised-tools payload asserts the table renders; the new callout is
gated on the zero-exercised state).
## Open Positions: raw float quantity + no "amount invested"

**Symptom:** The Open Positions row showed an unreadable quantity
(`0.0001681861435210638`) and never displayed how much cash was put in or what
the position is worth now — only Qty / Entry / Current / P&L. Operators could not
tell what they had invested, so a small `-$1.06` loss read as untrustworthy noise.

**Root cause:** `OpenPositionsPanel.tsx` rendered `positionQty(pos)` verbatim and
had no cost-basis / market-value columns. Entry × Qty (the cash invested) and
Current × Qty (current value) were never surfaced anywhere on the page.

**Fix:** `formatters.ts` adds `formatQuantity` (magnitude-aware precision:
≥1 → 4 dp, <1 → 8 dp, trailing zeros trimmed), `positionCostBasis`
(entry × |qty|) and `positionMarketValue` (live price × |qty|).
`OpenPositionsPanel.tsx` now formats the quantity and adds `Invested` and `Value`
columns with `title` tooltips spelling out each formula. Positions are already
live-marked, so the row is arithmetic-consistent: Value − Invested == P&L.

**Regression test:** `frontend/src/test/helpers/formatters.test.ts` —
`formatQuantity`, `positionCostBasis`, `positionMarketValue` suites (incl. the
`0.0001681861435210638` → `0.00016819` case and the $11.28 cost-basis case).

## Live Activity feed: every row reads "Market event" with no detail

**Symptom:** The Live Activity feed showed dozens of identical, indistinguishable
rows — `MARKET · Market event` with no symbol, price, or direction — making the
feed look random and untrustworthy ("what event happened?").

**Root cause:** `useCodexStore.trackWsMessage` only persisted
`{ stream, msgId, timestamp }` onto `RecentEvent`, discarding the `symbol` /
`price` / `change` that the backend already broadcasts on every `market_events`
frame (`websocket_broadcaster._transform_payload` → `type=price_update`).
`buildActivityTimeline` then had nothing to render, so it hard-coded
`detail: null` for every market row.

**Fix:** `RecentEvent` gains optional `symbol` / `price` / `change` / `eventType`;
`useGlobalWebSocket` extracts them from the frame (top-level for market frames,
nested `data`/`payload` otherwise) and passes them through `trackWsMessage`;
`activity-timeline.ts` adds `marketEventDetail` so a market row now reads
`BTC/USD · $60,781.58 · ▼ 12.30`. Falls back to `null` (prior behaviour) when a
frame carries no subject, so non-market events are unaffected.

**Regression test:** `frontend/src/test/helpers/activity-timeline.test.ts` —
`shows the symbol + price + direction for a market event (no more bare rows)`.

## Equity Curve shows "No equity data yet" while a position is open

**Symptom:** With an open position (live unrealized P&L moving every tick) the
Overview's Equity Curve still rendered "No equity data yet". It never reflected
the open position and was not real-time.

**Root cause:** `EquityCurve` built its series solely from filled `orders`'
realized `pnl` (`buildEquitySeries`). In memory mode / before any trade closes
there are no filled orders, so the series was empty — the open position's live
mark-to-market P&L was never plotted.

**Fix:** New `useLiveEquitySeries` hook samples the live total P&L
(`useLivePnl`, realized + mark-to-market unrealized) every 3s into a rolling,
capped window (pure `appendEquitySample`). `EquityCurve` takes an optional
`liveSeries` and falls back to it when the order-derived curve is empty, with a
"Live · marks to market in real time" badge. `DashboardView` wires the hook in.
A `ResizeObserver` stub was added to `src/test/setup.ts` because the chart now
renders in tests (recharts' ResponsiveContainer needs it in jsdom).

**Regression test:** `frontend/src/test/helpers/live-equity-series.test.ts`
(`appendEquitySample`) + `frontend/src/test/components/EquityCurve.test.tsx`
(`falls back to the live series when there are no closed orders`).

## Open Positions row doesn't tie out: Invested − Value ≠ P&L (off by a cent)

**Symptom:** A row showed Invested $11.28, Value $10.14, P&L −$1.15. Eyeballing
it, 11.28 − 10.14 = 1.14, not 1.15 — so the row read as "all wrong" / untrustworthy.

**Root cause:** Invested (entry×qty = 11.2818), Value (current×qty = 10.1364) and
P&L (−1.1454) are each *correctly* rounded to 2dp independently, but three
independently-rounded values don't satisfy `invested − value === −pnl` at display
precision.

**Fix:** `formatters.reconciledMarketValue(invested, pnl)` returns
`round(invested) + round(pnl)`, and `OpenPositionsPanel` uses it for the Value
column. P&L stays anchored to the live value shown in the header; Value is
derived so the row always ties out (11.28 − 10.13 = 1.15). Value tooltip updated
to "Invested + P&L".

**Regression test:** `frontend/src/test/helpers/formatters.test.ts` →
`reconciledMarketValue` ("makes the row tie out at 2dp").

## Equity Curve axes unreadable: repeated "11:25 AM" + junk Y labels; resets on reload

**Symptom:** The live equity curve's X-axis showed "11:25 AM" four times (all
samples within one minute), the Y-axis showed junk like -$0.15 / -$3.15 / -$6.15,
and a page reload wiped the curve back to a single dot.

**Root cause:** (1) X tick formatter was fixed HH:MM, so a sub-minute span
rendered identical labels. (2) `getPaddedDomain` padded with `max(range*0.12, 5)`
— a $5 floor around a −$1.15 value produced an oversized, un-rounded domain
([-6.15, 5]) and Recharts labelled it with junk. (3) The live series lived only
in component state, so a reload started it over.

**Fix:** `EquityCurve` — `getNiceYAxis` snaps the domain + explicit `ticks` to a
nice 1/2/5×10ⁿ step that always spans $0; the X formatter shows HH:MM:SS while
the span is < 5 min, then HH:MM. `useLiveEquitySeries` persists the rolling
window to `localStorage` (`codex.equityCurve`) and restores recent (< 1h) points
on mount via `loadPersistedEquitySeries`, so a reload keeps the curve.

**Regression test:** `frontend/src/test/components/EquityCurve.test.tsx`
(`produces clean, nicely-stepped y-axis ticks`) +
`frontend/src/test/helpers/live-equity-series.test.ts` (`loadPersistedEquitySeries`).

## Equity Curve hardening (review follow-ups)

**Symptom / risks found in review:** (1) reloading after the tab was away for
minutes spliced the old equity tail onto the new live point, drawing a fabricated
sloped segment across the gap; (2) the curve was re-serialized to localStorage on
every 3s sample; (3) sub-cent P&L (≈1e-7) could collapse every Y tick to 0 and
emit a negative-zero "-$0.00" label.

**Fix:** `useLiveEquitySeries` — `loadPersistedEquitySeries` now only restores when
the newest persisted sample is within `CONTINUITY_THRESHOLD_MS` (2 min); past
that it starts fresh, so a reload either continues a current curve or begins a
clean one (never a fabricated jump). Persistence moved to a fixed 15s cadence
(`PERSIST_INTERVAL_MS`) plus a flush on unmount, instead of writing on every
sample. `EquityCurve.getNiceYAxis` floors the tick step at $0.01 and normalizes
`-0` to `0`. The Open Positions `Value` column documents that for shorts it shows
cost-basis + P&L (the tie-out) rather than buy-back market value.

**Regression tests:** `frontend/src/test/helpers/live-equity-series.test.ts`
(`starts fresh when the newest point is stale`) +
`frontend/src/test/components/EquityCurve.test.tsx` (`floors the step at $0.01…`) +
`frontend/src/test/store/recent-events.test.ts` (WS detail threading).

## Equity Curve "just moves live between minutes — can't see anything" (Robinhood-style ranges)

**Symptom:** The Equity Curve only ever showed a ~10-minute live mark-to-market
window. With a flat open position it read as a near-horizontal line auto-zoomed to
a couple of cents of range, with no way to zoom out or see the full history — "this
one is just moving live in between minutes, I can't see shit."

**Root cause:** Three compounding limits. (1) `useLiveEquitySeries` capped the live
tail at 200 points / ~10 min (`MAX_POINTS`) and discarded the whole persisted curve
on reload whenever the newest sample was older than `CONTINUITY_THRESHOLD_MS`
(2 min), so there was never more than a few minutes to look at. (2) `EquityCurve`
showed *either* the realized order curve *or* the live tail, never the combined
lifetime, and had no time-range control. (3) The Y-axis auto-scaled a flat curve so
tiny moves filled the panel and looked like noise.

**Fix:** `EquityCurve` is now a Robinhood-style chart:
- `buildCombinedSeries(orders, liveSeries)` merges the realized order backbone
  (full history, one step per closed trade) with the live mark-to-market tail into
  one lifetime series — the live total already includes realized P&L, so the seam is
  continuous.
- A `LIVE / 1H / 1D / 1W / 1M / ALL` range selector (`filterByRange`) slices that
  series; ranges longer than the available history are disabled at cold start so the
  tabs aren't all identical. Default is `ALL` ("see everything").
- Window-relative stats (`computeWindowStats`): the headline change and line colour
  are measured from the baseline just before the visible window (Robinhood-style),
  with a zero baseline at inception so `ALL` equals the current total P&L (preserves
  the prior zero-baseline Net/colour semantics).
- `buildRenderSeries` inserts a null break between live samples more than
  `LIVE_GAP_BREAK_MS` (45s) apart, so a reload/background gap renders as a break
  rather than a fabricated diagonal — the realized backbone and realized→live seam
  are never broken.
- `useLiveEquitySeries` raises retention to `MAX_POINTS = 1200` (~1h at 3s) and
  `MAX_AGE_MS = 24h`. **This reverses the earlier "start fresh when the newest
  sample is stale" behaviour** (`CONTINUITY_THRESHOLD_MS`, see entry above): that
  rule threw away the history the new ranges need on every reload. The
  fabricated-slope risk it guarded against is now handled by the line-break in
  `buildRenderSeries` instead, so we keep the history *and* avoid the fake jump.

Note: a pure-live position (no closed trades) still maxes out at ~1h of continuous
data; the longer ranges fill in from the realized order history as trades close. A
truly continuous multi-day mark-to-market curve would need server-side equity
sampling (future work).

**Regression test:** `frontend/src/test/components/EquityCurve.test.tsx`
(`buildCombinedSeries`, `filterByRange`, `computeWindowStats`, `buildRenderSeries`,
`EquityCurve range selector`) + `frontend/src/test/helpers/live-equity-series.test.ts`
(`retains well past the old 200-point cap`, `restores history even when the newest
sample is no longer current`).

## Equity Curve "looks like a kid / bullshit" — gridded chart instead of the Robinhood line

**Symptom:** Even after the range tabs landed, the chart read as amateurish: the
same dollar value repeated ~4× (headline + Net/Peak/Range tiles), a heavy red
area "block" filling from the line up to $0, 8–9 cramped dollar gridlines, and —
for an all-underwater P&L — the line crammed against the bottom with a big dead
gap up to the $0 line.

**Root cause:** It was styled as a dense dashboard chart, not the Robinhood line
the user asked for. Two specifics: (1) the fill used the default base (≈$0) so a
−$1.10 curve drew a solid band between the line and $0; (2) `getNiceYAxis` always
forces $0 into the domain, so an all-negative curve was pushed to the bottom with
the $0 gridline stranded at the top.

**Fix:** `EquityCurve` is now the bare Robinhood line (the user picked the
"Robinhood-minimal line — no fill" option):
- Hidden Y-axis (no dollar labels), no `CartesianGrid`, no area fill —
  a single 2.5px line.
- `getLineDomain` fits the data (min..max) with a `MIN_DOMAIN_HALF` ($0.25) floor
  — it does **not** force $0 in — so a flat curve is a calm centred line, not
  amplified noise and not crammed to an edge.
- The baseline `ReferenceLine` uses `ifOverflow="discard"`, so the $0 / cost line
  appears only when the visible curve actually crosses it.
- Header shows the value once (headline) + a coloured arrow/period label; the
  signed change shows only on sub-windows. Range tabs are a full-width row below
  the chart.

Verified by rendering the real chart subtree to PNG (react-dom/server →
`@resvg/resvg-js`, installed `--no-save`, harness deleted after use) for the
uptrend / flat-loss / downtrend cases before shipping — the sandbox has no
browser, so this is how the look was checked rather than guessed.

**Regression test:** `frontend/src/test/components/EquityCurve.test.tsx`
(`getLineDomain` fits-data + min-height floor; `shows only the period label for
the all-time range`; `shows the signed change over a selected sub-window`).

## Neon-cyan accent + invalid colour in dark mode — duplicate `--accent` definition

**Symptom:** The logo, active-nav highlight, and watchlist selection rendered
neon cyan (`#00e5ff`) in light mode; in dark mode the same surfaces silently
lost their colour entirely (fell back to inherited text colour).

**Root cause:** `globals.css` declared `--accent` twice in `:root`: the
shadcn-style HSL triple (`214 28% 96%`, consumed as `hsl(var(--accent))` by
Tailwind) was clobbered by a terminal-token hex (`#00e5ff`) consumed as a raw
`var(--accent)` colour. `.dark` then re-set `--accent` back to an HSL triple,
which is an invalid value for raw `var(--accent)` reads — so dark mode dropped
the declaration. One variable, two incompatible consumers.

**Fix:** The brand/interactive colour is its own token, `--brand:
hsl(var(--primary))` (+ `--brand-soft`), so it can never collide with
Tailwind's `accent` colour and stays one consistent indigo in both themes.
`src/styles/globals.css`, `src/app/dashboard/layout.tsx`,
`src/components/dashboard/terminal/Watchlist.tsx`.

**Regression test:** none (pure CSS token wiring); the inline comment in
`globals.css` documents the constraint.

## Trace modal showed a red "Failed to load trace" for events that have no trace

**Symptom:** Clicking a system notification in the Live Decision Feed opened
the trace modal with a danger-toned "Failed to load trace"; the API response
was `404 {"detail":"Trace not found"}`.

**Root cause:** System notifications and rule-based fallback decisions carry a
`trace_id` but never write pipeline rows, so the backend's 404 is an expected
outcome — the modal treated every non-2xx as a hard failure.

**Fix:** `TraceModal` treats 404 as the benign empty-trace case and renders the
calm muted notice ("No pipeline trace was recorded for this event…"); the
danger-toned error is reserved for real API failures
(`src/components/dashboard/TraceModal.tsx`).

**Regression test:** `frontend/src/test/components/TraceModal.test.tsx::shows a
calm notice (not an error) when the backend has no trace (404)`
