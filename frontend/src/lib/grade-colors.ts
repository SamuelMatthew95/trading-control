/**
 * Grade display helpers — shared between learning and trading components.
 *
 * Centralising here ensures all panels use the same colour palette and
 * grade-to-badge mapping. Import from here; never re-define locally.
 *
 * CATEGORICAL PALETTE EXCEPTION: this module is the one sanctioned home for
 * hue literals on the grade axis. Grades are a five-way categorical scale, so
 * adjacent tiers need visually distinct hues (emerald/green/sky/amber/orange/
 * rose) that the four semantic Tone tokens cannot express. Every other
 * surface maps state to a Tone token (src/lib/design/sentiment.ts) — the
 * design-token guardrail test allowlists exactly this file.
 */

/** How often learning panels re-fetch data from the REST API. */
export const LEARNING_REFRESH_MS = 15_000

/** Chip shape for grade pills — compose the colour with gradeTone()/gradeBg(). */
export const gradeChipClass =
  'inline-flex items-center rounded border px-2 py-0.5 font-mono text-3xs font-semibold uppercase'

/**
 * Tailwind text-colour class for a single letter grade.
 *
 * A and B use separate greens so the two highest tiers are visually distinct
 * even when adjacent (emerald vs green). D and F use separate reds for the
 * same reason (orange vs rose).
 */
export function gradeColor(grade: string | null): string {
  switch (grade) {
    case 'A+': return 'text-emerald-600 dark:text-emerald-500'
    case 'A': return 'text-emerald-600 dark:text-emerald-500'
    case 'B': return 'text-green-600 dark:text-green-400'
    case 'C': return 'text-amber-600 dark:text-amber-500'
    case 'D': return 'text-orange-600 dark:text-orange-500'
    case 'F': return 'text-rose-600 dark:text-rose-500'
    default:  return 'text-muted-foreground'
  }
}

/** Tailwind background+border+text badge classes for a letter grade. */
export function gradeBg(grade: string | null): string {
  switch (grade) {
    case 'A+': return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30'
    case 'A': return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30'
    case 'B': return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-500/10 dark:text-green-400 dark:border-green-500/30'
    case 'C': return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/30'
    case 'D': return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-400 dark:border-orange-500/30'
    case 'F': return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/30'
    default:  return 'bg-muted-foreground/10 text-muted-foreground border-muted-foreground/30'
  }
}

/**
 * Tailwind badge classes for the trade-feed grade pill in TradingView.
 *
 * Uses sky for B (not green) to differentiate from the emerald A tier on a
 * white card background where green-on-emerald contrast is too low.
 */
export const GRADE_STYLES: Record<string, { badge: string }> = {
  A: { badge: 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500/30' },
  B: { badge: 'bg-sky-500/15 text-sky-600 dark:text-sky-300 ring-1 ring-sky-500/20' },
  C: { badge: 'bg-amber-500/20 text-amber-600 dark:text-amber-400 ring-1 ring-amber-500/30' },
  D: { badge: 'bg-rose-500/15 text-rose-500 ring-1 ring-rose-500/20' },
  F: { badge: 'bg-rose-500/20 text-rose-600 ring-1 ring-rose-500/30' },
}

/**
 * Promotion-tier badge classes. A tier is the standing an agent earns from its
 * sustained grade (see api/constants.GRADE_TO_TIER): PROMOTED agents are doing
 * well; PROBATION / UNDER_REVIEW are struggling; UNRATED has no data yet.
 * Centralised here so the scorecard and drill-in render tiers identically.
 */
export function tierBadge(tier: string): string {
  switch (tier) {
    case 'PROMOTED': return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30'
    case 'TRUSTED': return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/30'
    case 'STANDARD': return 'bg-muted-foreground/10 text-foreground/70 border-muted-foreground/30'
    case 'PROBATION': return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/30'
    case 'UNDER_REVIEW': return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/30'
    default: return 'bg-muted-foreground/10 text-muted-foreground border-muted-foreground/30'
  }
}

/** Human-readable tier label, e.g. "UNDER_REVIEW" → "Under Review". */
export function tierLabel(tier: string): string {
  return tier
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/**
 * Outlined chip classes for a letter grade, tolerant of +/- modifiers and
 * non-grades ("A+", "C-", "NR", null all resolve). Translucent fill + toned
 * border, for dense chip rows (cognitive dashboard, learning console).
 */
export function gradeTone(grade: string | null | undefined): string {
  const letter = (grade ?? '').trim().charAt(0).toUpperCase()
  switch (letter) {
    case 'A':
      return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
    case 'B':
      return 'bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30'
    case 'C':
      return 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
    case 'D':
      return 'bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30'
    case 'F':
      return 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30'
    default:
      return 'bg-muted-foreground/10 text-muted-foreground border-muted-foreground/20'
  }
}
