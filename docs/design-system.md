# Frontend Design System — "Axis Terminal" look

> Lives in `frontend/`. This documents the trading-terminal visual language as it
> is **actually implemented in this repo** (Next.js 14 App Router, TypeScript,
> Tailwind 3, shadcn/ui, recharts). It is the port of the external hand-off
> artifact, reconciled with this codebase's existing token system.

## 0. Principles (the "feel")

1. **Dark-first.** Deep navy canvas (`#020617` = `slate-950`), panels one step
   lighter (`#0F172A` = `slate-900`), raised surfaces (`#1E293B` = `slate-800`).
   A light theme still exists (`ThemeToggle` / `next-themes`, `defaultTheme="dark"`),
   but dark is the star and the slate-950/900/800 scale already *is* the terminal palette.
2. **One accent — cyan.** Cyan is the only brand / active / focus colour (the
   `--primary` token + focus `--ring`). Dark mode uses neon `#00E5FF`; light mode
   uses a darker cyan (`cyan-700`-ish) because the neon washes out on white. It is
   **never** used to mean "good".
3. **Green/red are direction & health only** — P&L, up/down ticks, pass/fail,
   live/offline. Never decorative. These are the `success` / `danger` tokens.
4. **Numbers are mono + tabular.** Prices, sizes, %, times, counts render in IBM
   Plex Mono with `tabular-nums` (`font-mono tabular-nums`, or the `.tabular`
   utility). This is ~half the "terminal" feel.
5. **Dense, panel-based, low-chrome.** Thin 1px `border-border` hairlines, tight
   padding, uppercase micro-labels with wide tracking, `h-7` controls.
6. **Tokenised.** Change a token in `globals.css` / `tailwind.config.js`, not a
   component, to restyle. Route domain colour through the resolvers in
   `src/lib/dashboard-helpers.ts` and `src/lib/design/sentiment.ts`.

## 1. Tokens — the single source of truth

Colours are **HSL** CSS vars (shadcn `H S% L%` space-separated form) declared in
`src/styles/globals.css` and exposed to Tailwind in `tailwind.config.js` as
`hsl(var(--x) / <alpha-value>)` so opacity modifiers work (`bg-primary/15`,
`ring-ring/60`, `border-primary/30`).

| Role | Token | Light | Dark | Hex |
|------|-------|-------|------|-----|
| Canvas / background | `--background` | slate-100 | `222 84% 5%` | `#020617` |
| Panel / card | `--card` | white | `222 47% 11%` | `#0F172A` |
| Raised / popover | `--popover` | white | `217 33% 18%` | `#1E293B` |
| Text / foreground | `--foreground` | navy | `210 40% 98%` | `#E2E8F0` |
| Muted text | `--muted-foreground` | — | `215 20% 65%` | `#94A3B8` |
| Border / input | `--border` `--input` | — | `217 33% 18%` | `#1E293B` |
| **Accent (primary + ring)** | `--primary` `--ring` | `193 82% 31%` | `187 100% 50%` | `#00E5FF` (dark) |
| Up / success | `--success` | — | `158 64% 52%` | `#10B981` |
| Down / danger | `--danger` | — | `351 95% 71%` | `#F43F5E` |
| Warning | `--warning` | — | `43 96% 56%` | `#FBBF24` |

`--primary-foreground` is deep navy (`222 47% 11%`) so text reads on the bright
cyan fill (e.g. a `bg-primary text-primary-foreground` CTA).

## 2. Fonts

Loaded in `src/app/layout.tsx` via `next/font/google` → CSS vars `--font-sans`
(Inter) and `--font-mono` (IBM Plex Mono), wired into Tailwind `fontFamily`.
Wrap any number in `font-mono tabular-nums`.

## 3. Primitives

- **Panel** = `Card` (`src/components/ui/card.tsx`) — slate-900 panel, thin
  border, dense padding. Shared dashboard surfaces use `cardClass` /
  `consolePanelClass` in `src/lib/dashboard-styles.ts` (panel lifts off the
  canvas: `dark:bg-slate-900` on the `dark:bg-slate-950` body).
- **Button** (`src/components/ui/button.tsx`) — `h-7` mono uppercase; cyan
  focus ring (`focus-visible:ring-ring/60`). Use `variant="destructive"` for
  Emergency Stop / Kill Switch.
- **Badge** (`src/components/ui/badge.tsx`) — `default`/`link` use the cyan
  `primary` token; `destructive`→rose. Domain badges route through
  `TONE_BADGE` (`src/lib/design/sentiment.ts`).
- **Status colour** — never hardcode. `sentimentTextClass(value)` for signed
  numbers; `TONE_TEXT` / `TONE_DOT` / `TONE_BADGE` for status vocabularies;
  the value helpers in `dashboard-helpers.ts` for domain → token.

## 4. Chrome

`src/app/dashboard/layout.tsx`: cyan brand glyph in `bg-primary/15`, active nav
item = `bg-primary/10 text-primary` + a 2px cyan left bar, a live mono clock and
a slim terminal **status bar** footer (connection dot + mode + P&L).

## 5. Charts

recharts, themed to the palette: axis ticks `#94a3b8` (muted), tooltip on
`#0f172a` (panel) with `#334155` border, curve coloured by **direction**
(`#10b981` up / `#f43f5e` down) — see `src/components/dashboard/EquityCurve.tsx`.

## 6. Do-not list

- ❌ No new standalone `.html` mockups — extend pages/components.
- ❌ No hardcoded `slate-*/emerald-*/rose-*/indigo-*` for *meaning* — use tokens.
- ❌ Green/red for anything except direction/health.
- ❌ A second accent — cyan only. (Categorical legends — stream badges, proposal
  routing — may use a fixed multi-hue palette; that is not an "accent".)
- ✅ Numbers always `font-mono tabular-nums`.
- ✅ Change a token, not a component, to restyle.
