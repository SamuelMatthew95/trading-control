# Frontend — Next.js 14 Context

> Lazy-loaded: only active when working in `frontend/`

## Tech Stack
- Next.js 14, TypeScript (strict mode), Tailwind CSS
- Package manager: pnpm

## API Calls
- Use `NEXT_PUBLIC_API_URL` env var — never hardcode backend URLs or ports
- Dashboard state: `GET /dashboard/state`
- WebSocket: real-time agent status + price updates

## TypeScript Rules
- No `any` types — `@typescript-eslint/no-explicit-any` is an **error** (tests exempt)
- Use `interface` for object shapes, `type` for unions/intersections
- All API response types must match backend Pydantic schemas

## Linting & Build
```bash
cd frontend && pnpm lint    # ESLint check (next lint --max-warnings 0)
cd frontend && pnpm build   # TypeScript + build verification
cd frontend && pnpm test    # vitest run
```

## Environment variables
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000  # dev
NEXT_PUBLIC_DEBUG_LOGS=true                # optional: verbose logger output in prod builds
# Vercel: set in project settings, never in code
```

## Logging — createLogger only (single console gateway)

All logging routes through `createLogger(namespace)` from `src/lib/logger.ts`.
Raw `console.*` is an ESLint **error** everywhere else, and the guardrail test
re-enforces it. Levels: `debug`/`info` are dev-only (production opt-in via
`NEXT_PUBLIC_DEBUG_LOGS=true` or `localStorage.setItem('tc:debug','1')` for
live WS diagnostics without a redeploy); `warn`/`error` always emit.

```ts
import { createLogger } from '@/lib/logger'
const log = createLogger('WS')
log.info('Connecting to', url)   // "[WS] Connecting to …"
```

## Design System — semantic tokens (single source of truth)

The UI maps **state → Tone → design token → presentation**, so the colour palette
and light/dark parity live in exactly one place. Never hardcode a semantic colour.

- **Tone** (`src/lib/design/sentiment.ts`): `'success' | 'danger' | 'warning' | 'neutral'`.
  `Sentiment` (`positive|negative|neutral`) is the directional subset; `sentimentOf(value)` maps
  a signed number to it via the shared `SENTIMENT_EPSILON` dead-band (no magic numbers in callers).
- **Colour tokens** (`tailwind.config.js` + `src/styles/globals.css`): every colour is a CSS-var
  token flipped light/dark **once** in `globals.css`. Semantic: `success`/`danger`/`warning`.
  Chrome: `background` (page) < `card` (panel) < `popover` (modal) surfaces; `border` (default —
  the bare `border`/`divide-y` utilities already render it, never add a border colour class),
  `border-strong` (hover step), `muted`/`muted-foreground`, `foreground` (alpha-capable:
  `text-foreground/70`), `brand` (interactive accent, `text-brand`/`bg-brand/10`), `ring` (focus).
  Use `text-success`, `bg-danger/10`, `text-muted-foreground` — no `dark:` pairs.
- **Type scale**: `text-2xs` (11px) and `text-3xs` (10px) are the only sub-`xs` sizes;
  uppercase labels use `tracking-caps` (0.16em) or `tracking-caps-wide` (0.2em). Arbitrary
  `text-[Npx]`/`tracking-[…]` values are forbidden (guardrail-enforced).
- **Stacking scale**: `z-sticky`/`z-overlay`/`z-sidebar`/`z-header`/`z-toast`/`z-modal` —
  numeric `z-*` utilities are forbidden (guardrail-enforced).
- **Shadows/animations**: `shadow-card`, `shadow-modal` (themed via CSS vars);
  `animate-fade-in`, `animate-scale-in` for overlays.
- **Canonical shape maps** (`src/lib/design/sentiment.ts`): `TONE_TEXT`, `TONE_DOT`,
  `TONE_BADGE`, `TONE_BADGE_OUTLINED`, `TONE_BUTTON`. Compose shape (padding/radius) at the
  call site; never re-declare the colour recipe.
- **Resolvers** (`src/lib/dashboard-helpers.ts`): value helpers (`pnlColorClass`,
  `sentimentTextClass`, `confColorClass`, `actionBadgeClass`, `actionTextClass`, `toneForAction`,
  `meterFillClass`, `scoreColorClass`, `proposalStatusClass`/`proposalStatusTone`, …)
  resolve a domain value → token. Add colour logic here, routed through the Tone maps —
  never a new per-component `*Color`/`*Tone`/`*Badge` helper.
- **Categorical palettes** (the only sanctioned hue literals): multi-way legends the four
  Tones cannot express. Module-level: `src/lib/grade-colors.ts` (grade axis A–F). Line-level:
  a `// categorical-hue: <reason>` marker (e.g. the activity-timeline stage legend). The
  guardrail test honours exactly these two escapes.
- **Status vocabulary**: the canonical agent lifecycle type is `AgentStatus` (`@/types/dashboard`);
  `PipelineAgentStatus` aliases it. Don't re-declare `'Live'|'Stale'|'Error'|'Idle'` locally.

## Shared primitives (`src/components/ui/`) — compose, never re-declare

- `Button` — variant `outline|ghost|tonal|solid`, `tone`, size `xs|sm|icon|icon-sm`. Every
  styled `<button>` composes this (focus ring, disabled state, hover included).
- `Badge` — `tone`, variant `soft|outlined`, size `xs|sm`, `pill`. All semantic chips/pills.
- `Meter` — the ONLY sanctioned inline `style` (data-driven fill width). All progress bars.
- `Modal` — overlay + panel + header + close + Escape + dialog ARIA. All dialogs.
- `Card` — `cardClass` surface + title/meta header row. `StatTile`/`MetricTile` — KPI tiles.
- `EmptyState` / `LoadingState` / `Skeleton` — every empty/loading rendering.
- `PageHeader` — eyebrow/h1/description card every dashboard section opens with.
- `Table*` (`ui/table.tsx`) — canonical table slots.
- Surface class constants live in `src/lib/dashboard-styles.ts` (`cardClass`,
  `sectionTitleClass`, `mutedClass`, `valueClass`, `consolePanelClass`, `errorTextClass`,
  `chipClass`, …); the terminal uses `terminal/Panel.tsx`.

## UI copy — `src/constants/copy.ts` (UI_COPY + NO_DATA)

Every user-visible string (headings, labels, buttons, tooltips, aria-labels, empty states,
banners, fallback words) lives in `UI_COPY.<surface>.<key>` — never inline in JSX. Missing-data
glyphs use `NO_DATA` ('--'). Dynamic sentences keep their interpolation in the component but
reuse stems from the registry.

## Shared hooks

`usePolledApi(path, intervalMs)` (`src/hooks/usePolledApi.ts`) is the canonical
fetch-on-mount + interval-refresh + keep-last-good-data pattern — never hand-roll the
useEffect/setInterval/cancelled-flag dance in a panel. Aggregate poller: `useRestPoll`.

### Guardrail test (run after any styling/logging change)
`src/test/guardrails/design-system.test.ts` scans non-test source and fails on:
hardcoded semantic colour classes (outside the categorical escapes), raw `console.*`
outside `src/lib/logger.ts`, raw `var(--accent` reads, inline `style={…}` outside
`ui/meter.tsx`, arbitrary `text-[Npx]`/`tracking-[…]` utilities, and numeric `z-*` utilities.

## Shared formatters (`src/lib/formatters.ts`)
One canonical implementation each — `formatTimeAgo` (relative ages, injectable clock),
`formatAgeFromMs`, `formatUSD`/`signedUSD`, `formatPercent`, `formatQuantity`,
`parseTimestampMs`, position P&L helpers. Import from here; never re-define locally
(there were once three diverging time-ago implementations).

## Anti-patterns
- ❌ Hardcoded semantic colours (`text-emerald-600`, `bg-rose-500 dark:bg-rose-400`) → map state to a `Tone` and use the token (`text-success`, `bg-danger/10`); see Design System above
- ❌ Raw slate light/dark pairs (`text-slate-500 dark:text-slate-400`) → chrome tokens (`text-muted-foreground`, `text-foreground/70`, default `border`, `bg-card`, `bg-muted`)
- ❌ Inline `style={{ … }}` props → tokens/classes; data-driven widths use `<Meter>`
- ❌ Hardcoded UI strings in JSX (labels, tooltips, empty states, aria-labels) → `UI_COPY` in `src/constants/copy.ts`; `'--'` → `NO_DATA`
- ❌ Ad-hoc `<button>`/chip/modal/progress-bar/stat-tile recipes → shared `ui/` primitives
- ❌ Arbitrary `text-[Npx]` / `tracking-[…]` / numeric `z-*` utilities → configured scales
- ❌ Hand-rolled useEffect+setInterval polling in panels → `usePolledApi`
- ❌ Local `relTime`/`timeAgo`/`fmtUSD`/`fmtPct` helpers → `src/lib/formatters.ts`
- ❌ New per-component `*Color` / `*Tone` / `*Badge` helpers → route through the shared resolvers in `dashboard-helpers.ts` / the Tone maps
- ❌ Re-declaring status unions (`'Live'|'Stale'|'Error'|'Idle'`, LLM status, …) locally → import the canonical type
- ❌ Template-literal Tailwind classes (`` `bg-${tone}/10` ``) → Tailwind's JIT only sees static strings; write literals
- ❌ Hardcoded `localhost:8000`, `onrender.com`, or `vercel.app` URLs in source
- ❌ `console.*` anywhere except `src/lib/logger.ts` → use `createLogger`
- ❌ Skipping TypeScript strict checks with `@ts-ignore` or `any`
