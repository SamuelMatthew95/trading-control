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

## Design System — semantic Tone tokens (single source of truth)

The UI maps **state → Tone → design token → presentation**, so the colour palette
and light/dark parity live in exactly one place. Never hardcode a semantic colour.

- **Tone** (`src/lib/design/sentiment.ts`): `'success' | 'danger' | 'warning' | 'neutral'`.
  `Sentiment` (`positive|negative|neutral`) is the directional subset; `sentimentOf(value)` maps
  a signed number to it via the shared `SENTIMENT_EPSILON` dead-band (no magic numbers in callers).
- **Tokens** (`tailwind.config.js` + `src/styles/globals.css`): `success`/`danger`/`warning`
  are CSS-var Tailwind colours (`hsl(var(--success))`) flipped light/dark **once** in `globals.css`.
  Use `text-success`, `bg-danger/10`, `border-warning/30` — no `dark:` pairs.
- **Canonical shape maps** (`src/lib/design/sentiment.ts`): `TONE_TEXT` (text), `TONE_DOT`
  (status dots), `TONE_BADGE` (translucent chip), `TONE_BADGE_OUTLINED` (chip/banner with
  toned border). Compose shape (padding/radius) at the call site; never re-declare the
  colour recipe.
- **Resolvers** (`src/lib/dashboard-helpers.ts`): value helpers (`pnlColorClass`,
  `sentimentTextClass`, `confColorClass`, `actionBadgeClass`, `proposalStatusClass`, …)
  resolve a domain value → token. Add colour logic here, routed through the Tone maps —
  never a new per-component `*Color`/`*Tone`/`*Badge` helper.
- **Categorical palettes** (the only sanctioned hue literals): multi-way legends the four
  Tones cannot express. Module-level: `src/lib/grade-colors.ts` (grade axis A–F). Line-level:
  a `// categorical-hue: <reason>` marker (e.g. the activity-timeline stage legend). The
  guardrail test honours exactly these two escapes.
- **Brand colour**: `var(--brand)` / `var(--brand-soft)` (derived from `--primary`). NEVER
  read `var(--accent)` as a colour — Tailwind consumes `--accent` as an HSL triple, so a raw
  read is invalid CSS in dark mode (this was a live bug; see docs/troubleshooting/frontend.md).
- **Status vocabulary**: the canonical agent lifecycle type is `AgentStatus` (`@/types/dashboard`);
  `PipelineAgentStatus` aliases it. Don't re-declare `'Live'|'Stale'|'Error'|'Idle'` locally.

### Guardrail test (run after any styling/logging change)
`src/test/guardrails/design-system.test.ts` scans non-test source and fails on:
hardcoded semantic colour classes (outside the categorical escapes), raw `console.*`
outside `src/lib/logger.ts`, and raw `var(--accent` reads.

## Shared formatters (`src/lib/formatters.ts`)
One canonical implementation each — `formatTimeAgo` (relative ages, injectable clock),
`formatAgeFromMs`, `formatUSD`/`signedUSD`, `formatPercent`, `formatQuantity`,
`parseTimestampMs`, position P&L helpers. Import from here; never re-define locally
(there were once three diverging time-ago implementations).

## Anti-patterns
- ❌ Hardcoded semantic colours (`text-emerald-600`, `bg-rose-500 dark:bg-rose-400`) → map state to a `Tone` and use the token (`text-success`, `bg-danger/10`); see Design System above
- ❌ New per-component `*Color` / `*Tone` / `*Badge` helpers → route through the shared resolvers in `dashboard-helpers.ts` / the Tone maps
- ❌ Re-declaring status unions (`'Live'|'Stale'|'Error'|'Idle'`, LLM status, …) locally → import the canonical type
- ❌ Template-literal Tailwind classes (`` `bg-${tone}/10` ``) → Tailwind's JIT only sees static strings; write literals
- ❌ Hardcoded `localhost:8000`, `onrender.com`, or `vercel.app` URLs in source
- ❌ `console.*` anywhere except `src/lib/logger.ts` → use `createLogger`
- ❌ Skipping TypeScript strict checks with `@ts-ignore` or `any`
