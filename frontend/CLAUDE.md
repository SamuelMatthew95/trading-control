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
- No `any` types without an explanatory comment
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
# Vercel: set in project settings, never in code
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
- **Resolvers** (`src/lib/dashboard-helpers.ts`): `TONE_TEXT[tone]` / `SENTIMENT_TEXT[sentiment]`,
  and value helpers (`pnlColorClass`, `sentimentTextClass`, `pipelineStatusTextClass`,
  `confColorClass`, `agentCardTextClass`, …) resolve a domain value → token. Add colour logic
  here, routed through `TONE_TEXT` — never a new per-component `*Color`/`*Tone`/`*Badge` helper.
- **Status vocabulary**: the canonical agent lifecycle type is `AgentStatus` (`@/types/dashboard`);
  `PipelineAgentStatus` aliases it. Don't re-declare `'Live'|'Stale'|'Error'|'Idle'` locally.

> Migration in progress (PR #286): directional + text-colour categories are token-driven; the
> badge / dot / status-tone categories still hold legacy literals and are being folded onto `Tone`.

## Anti-patterns
- ❌ Hardcoded semantic colours (`text-emerald-600`, `bg-rose-500 dark:bg-rose-400`) → map state to a `Tone` and use the token (`text-success`, `bg-danger/10`); see Design System above
- ❌ New per-component `*Color` / `*Tone` / `*Badge` helpers → route through the shared resolvers in `dashboard-helpers.ts`
- ❌ Re-declaring status unions (`'Live'|'Stale'|'Error'|'Idle'`, LLM status, …) locally → import the canonical type
- ❌ Hardcoded `localhost:8000`, `onrender.com`, or `vercel.app` URLs in source
- ❌ `console.log` left in production code
- ❌ Skipping TypeScript strict checks with `@ts-ignore`
