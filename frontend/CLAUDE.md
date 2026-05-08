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
cd frontend && pnpm lint        # ESLint check (--max-warnings 0)
cd frontend && pnpm type-check  # tsc --noEmit
cd frontend && pnpm test        # vitest
cd frontend && pnpm build       # Next.js production build
```

## Environment variables
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000  # dev
# Vercel: set in project settings, never in code
```

## Anti-patterns
- ❌ Hardcoded `localhost:8000`, `onrender.com`, or `vercel.app` URLs in source
- ❌ `console.log` left in production code
- ❌ Skipping TypeScript strict checks with `@ts-ignore`
- ❌ Raw `fetch()` in components — use `lib/api/*` typed wrappers
- ❌ Inline color classes (`bg-emerald-500/10 text-emerald-600`) — use `TONE_CLASSES[tone]` from `lib/state`
- ❌ Duplicate formatters — every formatter lives in `lib/format/*`
- ❌ Repeated Tailwind chains (2+ occurrences) — promote to `lib/styles/dashboard.ts`
- ❌ Inline JSX components defined inside another component's body — extract to a named function component

## Architecture
The dashboard surface follows a strict layered architecture:

```
pages → DashboardView → SectionN → TerminalCard / MetricTile / StatusChip
                          ↑
                          ├── lib/dashboard/selectors  (pure view-model derivation)
                          ├── lib/api/*               (typed REST wrappers)
                          ├── hooks/useDashboardData  (consolidated REST polling)
                          ├── lib/format              (currency / percent / date / number)
                          ├── lib/state               (Tone vocabulary + toneFor*)
                          ├── lib/styles              (named class bundles — INNER_TILE etc.)
                          └── lib/constants           (UI tokens, agent thresholds, tickers)
```

See **`STRUCTURE.md`** in this directory for the full folder map, layer
rules, data flow, invariants, and "adding a new section" guide.

## Test layout
- `lib/format/__tests__/`     — formatters
- `lib/state/__tests__/`      — tone + status helpers
- `lib/dashboard/__tests__/`  — view-model selectors
- `lib/styles/__tests__/`     — guardrails against re-introducing inline class chains
- `components/terminal/__tests__/` — primitives
- `components/trading/__tests__/`  — domain primitives (PnL, TradeSideChip, GradeChip)
- `src/test/`                       — legacy DashboardView / TradeFeed / EquityCurve tests
