# Frontend Architecture

> Operator-grade trading dashboard. Dense, deterministic, state-driven. No
> gradients, no marketing pills, no purple SaaS palette, no fake demo data.

This document describes how the dashboard is organized after the
[claude/refactor-frontend-architecture-q3tWq] refactor. It's the entry point
for understanding *where things live* and *what rule each layer follows*.

## Folder map

```
frontend/src/
├── app/
│   └── dashboard/
│       ├── DashboardView.tsx          ← composition only (~270 LOC)
│       ├── layout.tsx                 ← shell (sidebar, header, kill switch)
│       ├── page.tsx                   ← /dashboard
│       ├── trading/page.tsx           ← /dashboard/trading
│       ├── agents/page.tsx            ← /dashboard/agents
│       ├── learning/page.tsx          ← /dashboard/learning
│       ├── system/page.tsx            ← /dashboard/system
│       └── types.ts                   ← `Section` enum
│
├── components/
│   ├── terminal/                      ← generic operator-style UI primitives
│   │   ├── TerminalCard.tsx
│   │   ├── SectionHeader.tsx
│   │   ├── StatusChip.tsx
│   │   ├── StateIndicator.tsx
│   │   ├── MetricTile.tsx
│   │   ├── EmptyState.tsx
│   │   ├── LoadingState.tsx
│   │   ├── ErrorState.tsx
│   │   └── TerminalTable.tsx          (TerminalRow, TerminalCell)
│   │
│   ├── trading/                       ← trading-domain primitives
│   │   ├── TradeSideChip.tsx          (BUY/SELL/LONG/SHORT)
│   │   ├── GradeChip.tsx              (A/B/C/D/F)
│   │   └── PnlValue.tsx               (signed currency + tone)
│   │
│   └── dashboard/
│       ├── sections/                  ← per-screen panels & their sub-rows
│       │   ├── OverviewSection.tsx
│       │   ├── TradingSection.tsx
│       │   ├── AgentsSection.tsx
│       │   ├── LearningSection.tsx
│       │   ├── SystemSection.tsx
│       │   ├── TraceModal.tsx
│       │   ├── TopMetricsRow.tsx
│       │   ├── PerformancePanel.tsx
│       │   ├── AgentMatrix.tsx
│       │   ├── LiveMarketPrices.tsx
│       │   ├── PriceTileSkeleton.tsx
│       │   ├── TradeFeedPanel.tsx
│       │   ├── PositionsTable.tsx
│       │   ├── AgentThoughtStream.tsx
│       │   ├── AgentStatusTable.tsx
│       │   ├── AgentInstancesPanel.tsx
│       │   ├── SystemDiagnosticsPanel.tsx
│       │   ├── ProposalsFeed.tsx
│       │   ├── LearningPipelineStatusPanel.tsx
│       │   ├── IcWeightsPanel.tsx
│       │   └── GradeHistoryPanel.tsx
│       ├── NotificationFeed.tsx       ← refactored to Tone system
│       ├── StatusBadge.tsx            ← thin wrapper over StatusChip
│       ├── AgentCard.tsx              ← uses TerminalCard
│       ├── MetricCard.tsx             ← thin wrapper over MetricTile
│       ├── LearningDashboard.tsx      ← legacy panel (preserved)
│       ├── LLMHealthPanel.tsx         ← legacy panel (preserved)
│       ├── EquityCurve.tsx            ← Recharts equity curve
│       ├── LearningLoopPanel.tsx
│       ├── LogPanel.tsx
│       ├── SignalsSidebar.tsx         ← refactored to apiFetch
│       └── TaskTable.tsx
│
├── hooks/
│   ├── useDashboardData.ts            ← consolidated REST polling
│   ├── usePollingFetch.ts             ← generic polling primitive
│   ├── useWebSocket.ts                ← WS connection
│   ├── useGlobalWebSocket.ts          ← WS message router
│   └── useSystemStatus.ts             ← derived "trading|booting|error|idle"
│
├── lib/
│   ├── format/                        ← FORMATTERS (only one impl per task)
│   │   ├── currency.ts                (formatCurrency / formatSignedCurrency / formatPnl)
│   │   ├── percent.ts                 (formatPercent / formatRatioAsPercent)
│   │   ├── date.ts                    (formatTimestamp / formatTimeAgo / formatDuration / formatUptime / parseTimestamp)
│   │   ├── number.ts                  (formatNumber / toFiniteNumber / MISSING)
│   │   ├── index.ts
│   │   └── __tests__/                 (44 tests)
│   │
│   ├── state/                         ← STATUS → TONE mapping
│   │   ├── tone.ts                    (Tone, TONE_CLASSES, getNumberTone)
│   │   ├── agentStatus.ts             (toneFor* helpers + isClosedTrade + pickHigherPriorityStatus)
│   │   ├── index.ts
│   │   └── __tests__/                 (36 tests)
│   │
│   ├── styles/                        ← CENTRALIZED CLASS BUNDLES
│   │   ├── dashboard.ts               (INNER_TILE, CHIP_BASE, TRACE_BUTTON, …)
│   │   ├── index.ts
│   │   └── __tests__/                 (guardrail audit)
│   │
│   ├── types/                         ← shared API & view-model types
│   │   ├── api.ts
│   │   ├── dashboard.ts
│   │   └── index.ts
│   │
│   ├── constants/                     ← UI tokens, agent thresholds, tickers,
│   │   │                                 fallback labels, proposal taxonomy,
│   │   │                                 polling cadences
│   │   ├── ui.ts                      (UI_RADIUS, UI_TEXT, UI_SURFACE, UI_PAD)
│   │   ├── trading.ts                 (TICKER_SYMBOLS, PRICE_LIVE_WINDOW_MS)
│   │   ├── agentStates.ts             (AGENT_LIVE/STALE thresholds, displayAgentName)
│   │   ├── learning.ts                (FALLBACK_LABELS, FALLBACK_MESSAGES,
│   │   │                                 PROPOSAL_TYPE_LABEL/_TONE,
│   │   │                                 SHARPE_GREAT/_NEUTRAL_THRESHOLD,
│   │   │                                 RECENT_EVENT_TONE,
│   │   │                                 PIPELINE_STREAM_NAMES,
│   │   │                                 PIPELINE_FRESH_WINDOW_MS,
│   │   │                                 STREAM_LIVE_WINDOW_MS)
│   │   └── polling.ts                 (DASHBOARD_STATE_POLL_MS,
│   │                                     DASHBOARD_DATA_POLL_MS,
│   │                                     LLM_HEALTH_POLL_MS,
│   │                                     SIGNALS_POLL_MS,
│   │                                     LEARNING_DASHBOARD_POLL_MS)
│   │
│   ├── api/                           ← typed REST wrappers
│   │   ├── dashboard.ts               (getDashboardState, getKillSwitch, …)
│   │   ├── learning.ts                (getLearningProposals, voteOnProposal, …)
│   │   └── index.ts
│   │
│   ├── dashboard/                     ← pure view-model derivation
│   │   ├── selectors.ts               (buildAgentSummaries, buildDashboardSummary, …)
│   │   ├── learning.ts                (buildLearningSummary, buildPipelineStages, …)
│   │   └── __tests__/                 (38 tests)
│   │
│   ├── apiClient.ts                   ← apiFetch<T>() + URL normalization
│   └── utils.ts                       ← cn()
│
├── stores/
│   └── useCodexStore.ts               ← Zustand store + WebSocket types
│
├── types/dashboard.ts                 ← legacy types kept for /TaskTable etc.
└── constants/notifications.ts         ← notification severity / fallbacks
```

## Layer rules

These rules are enforced by tests, not just convention. Breaking them fails CI.

### 1. Page files compose, they don't compute

`app/dashboard/page.tsx`, `trading/page.tsx`, etc. each render
`<DashboardView section="..." />` and nothing else. The dashboard view itself
calls `useDashboardData(wsConnected)` for REST polling, runs the selectors
in `lib/dashboard/`, and routes to a `Section*` component by `section` prop.

If a page file gains its own `useEffect` or `fetch`, that logic belongs in a
hook or selector instead.

### 2. Components render, hooks fetch

- Components in `components/terminal/`, `components/trading/`, and
  `components/dashboard/sections/` are presentational. They take props and
  produce JSX. They MAY be subscribed to a Zustand selector, but they MUST
  NOT issue raw `fetch` calls.
- All REST traffic goes through `lib/api/*` (typed wrappers around
  `apiFetch<T>()`). The styles-audit and guardrail tests fail if a raw
  `fetch(api(...))` reappears in a component.

### 3. Color comes from Tone, never from raw class strings

```tsx
// ✗ NEVER
<span className="bg-emerald-500/10 text-emerald-600">Live</span>

// ✓ Compose lib/state + lib/styles
import { TONE_CLASSES } from '@/lib/state'
import { CHIP_BASE } from '@/lib/styles'
<span className={cn(CHIP_BASE, TONE_CLASSES.pos.soft)}>Live</span>
```

The `Tone` vocabulary is `pos | neg | warn | info | muted`. To map a
domain status (agent state, grade letter, score, ratio, side) into a Tone,
use the `toneFor*` helpers in `lib/state`. Adding a new visual treatment
means adding a new tone — never picking a one-off color.

### 4. Repeated classNames live in `lib/styles`

If a Tailwind chain appears in 2+ places, it must be a named export in
`lib/styles/dashboard.ts`. Adding a new chain means adding a new constant.
The styles-audit test (`src/lib/styles/__tests__/styles-audit.test.ts`)
hard-fails CI if a banned inline pattern returns.

### 5. Formatting goes through `lib/format`

```tsx
// ✗ NEVER
`$${value.toFixed(2)}`         // raw template
formatUSD(value)               // duplicate impl

// ✓ Always
import { formatSignedCurrency, formatTimestamp, formatDuration } from '@/lib/format'
```

Missing values render as the em-dash placeholder (`MISSING = '—'`). Never
`NaN`, never fake `0`, never blank. Zero-or-near-zero P&L displays as
`$0.00` with no sign — the formatter handles the `-$0.00` artifact.

### 6. Inline lambdas → named function components

JSX rendered inside a `.map(...)` callback should call a named component,
not contain an inline arrow. Example:

```tsx
// ✗ Inline arrow with multiple lines of JSX
{positions.map((p, i) => (
  <tr key={i}>
    {/* 30 lines of cells */}
  </tr>
))}

// ✓ Extract to a named row component
function PositionRow({ position, index }: PositionRowProps) { ... }
{positions.map((p, i) => <PositionRow key={...} position={p} index={i} />)}
```

This makes the row component testable in isolation and unblocks reuse.

### 7. Constants — never hardcode magic numbers, labels, or lookup tables

Every recurring label, threshold, polling cadence, or `Record<string, X>`
lookup belongs in `lib/constants/*`. Components never declare them locally.

```tsx
// ✗ NEVER
const REFRESH_MS = 15_000
const PROPOSAL_TYPE_LABEL = { parameter_change: 'Param Change', ... }
const FALLBACK_LABELS = { skip_reasoning: 'Rule-based fallback decision', ... }

// ✓ Single source of truth
import { LEARNING_DASHBOARD_POLL_MS } from '@/lib/constants/polling'
import { PROPOSAL_TYPE_LABEL, FALLBACK_LABELS } from '@/lib/constants/learning'
```

Consequences:
- Tuning the dashboard's polling load = edit `lib/constants/polling.ts`.
- Adding a backend `proposal_type` = edit `lib/constants/learning.ts`.
- Renaming a fallback message = edit one file.
- Constants tests (`lib/constants/__tests__/*.test.ts`) catch shape drift —
  e.g. a proposal type missing its tone, a Sharpe threshold inversion.

### 8. Confidence is read through `extractConfidence`

Backend logs may emit confidence as `0.73`, `73`, or `confidence_score: 0.73`.
A component reading `log.confidence` directly will render `7300%` for the
second form and miss the third entirely. Always use the helper:

```tsx
import { extractConfidence } from '@/lib/format'
const confidence = extractConfidence(log)  // → 0–1 ratio or null
```

## Data flow at runtime

```
WebSocket (lib/useGlobalWebSocket)         REST polling (hooks/useDashboardData)
          │                                                 │
          ▼                                                 ▼
       Zustand store (stores/useCodexStore.ts)              │
          │                                                 │
          ▼                                                 ▼
       Pure selectors (lib/dashboard/selectors.ts, learning.ts)
          │
          ▼
       Section components (components/dashboard/sections/*)
          │
          ▼
       Terminal primitives + trading primitives (no logic)
```

The store holds raw data shapes from the backend. Selectors derive
view-models. Section components only render. This separation is what made
the 2133-line `DashboardView.tsx` collapse to ~270 lines.

## Tests

```
241 tests across 19 files (as of this commit)

src/lib/format/__tests__/format.test.ts             44  formatters
src/lib/state/__tests__/state.test.ts               36  tone helpers
src/lib/dashboard/__tests__/selectors.test.ts       26  view-model selectors
src/lib/dashboard/__tests__/learning.test.ts        12  learning selectors
src/lib/styles/__tests__/styles-audit.test.ts       10  guardrails
src/components/terminal/__tests__/StatusChip.test.tsx  6
src/components/terminal/__tests__/MetricTile.test.tsx  6
src/components/terminal/__tests__/EmptyState.test.tsx  8
src/components/trading/__tests__/PnlValue.test.tsx    16  PnlValue, TradeSideChip, GradeChip
src/test/components/* (existing)                    33
src/test/store/* (existing)                         22
src/test/helpers/sanitize.test.ts                   20
... (others)
```

Run with:

```bash
pnpm test          # all
pnpm lint          # ESLint (--max-warnings 0)
pnpm type-check    # tsc --noEmit
pnpm build         # full Next.js production build
```

## Known invariants

1. **Routes are unchanged**: `/dashboard`, `/dashboard/trading`,
   `/dashboard/agents`, `/dashboard/learning`, `/dashboard/system`. Each
   is a thin file that renders `<DashboardView section="..." />`.
2. **API contracts are unchanged**: every backend endpoint listed in
   `API_ENDPOINTS` is still consumed exactly as before — only the call
   sites moved into `lib/api/*`.
3. **WebSocket behavior is unchanged**: the singleton manager in
   `useGlobalWebSocket.ts` is untouched; only its consumers were tidied.
4. **Missing values render as `—`**, never `NaN`, never fake `0`.
5. **Heartbeat timing**: `AGENT_LIVE_THRESHOLD_MS = 10s` (override 90s for
   `REASONING_AGENT`); `AGENT_STALE_THRESHOLD_MS = 120s`. Above stale ⇒ Idle.
6. **`-$0.00` artifact does not exist**: zero or near-zero P&L always
   renders as `$0.00` with no sign.

## Adding a new section panel

1. Build a presentational component under `components/dashboard/sections/`.
   Use `TerminalCard`, `SectionHeader`, and any `lib/styles` constants.
2. If the data needs derivation, add a pure function to
   `lib/dashboard/selectors.ts` (or `learning.ts`) and a unit test.
3. If the panel polls REST, add a typed wrapper to `lib/api/*` and consume
   it from `useDashboardData` (don't fetch in the component).
4. Compose the panel into the relevant `Section*.tsx` file.
5. If you find yourself writing the same className twice — promote it to
   `lib/styles/dashboard.ts`.

## Adding a new status type

1. If the value maps cleanly to one of the existing tones, add a
   `toneFor*` helper in `lib/state/agentStatus.ts` and reference it.
2. Use `<StatusChip label="..." tone={toneFor*(value)} />` to render.
3. Never write a one-off `Record<Status, string>` color map in a component.
