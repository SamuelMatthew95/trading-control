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
cd frontend && npm run lint    # ESLint check
cd frontend && npm run build   # TypeScript + build verification
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
