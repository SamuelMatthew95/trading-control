# Frontend Troubleshooting

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
Redis `notifications:recent` backlog and caps it at 200 (`useCodexStore`), so the
length is the stored-history size, not recent activity — it pins at 200 on any
established session.

**Fix:** `components/dashboard/agents/AgentsDashboard.tsx` now shows
`countRecentNotifications(notifications, 1h)` as the headline ("Notifications · 1h")
with `N stored (max 200)` and the last-activity time as secondary context. The
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
the whole `decisions:recent` list (LTRIM-capped at 500). An established session
pins `total` at the 500 cap regardless of recent activity, so the two figures
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
