/**
 * Grade display helpers — shared between learning and trading components.
 *
 * Centralising here ensures all panels use the same colour palette and
 * grade-to-badge mapping. Import from here; never re-define locally.
 */

/** How often learning panels re-fetch data from the REST API. */
export const LEARNING_REFRESH_MS = 15_000

/**
 * Tailwind text-colour class for a single letter grade.
 *
 * A and B use separate greens so the two highest tiers are visually distinct
 * even when adjacent (emerald vs green). D and F use separate reds for the
 * same reason (orange vs rose).
 */
export function gradeColor(grade: string | null): string {
  switch (grade) {
    case 'A': return 'text-emerald-600 dark:text-emerald-500'
    case 'B': return 'text-green-600 dark:text-green-400'
    case 'C': return 'text-amber-600 dark:text-amber-500'
    case 'D': return 'text-orange-600 dark:text-orange-500'
    case 'F': return 'text-rose-600 dark:text-rose-500'
    default:  return 'text-slate-500 dark:text-slate-400'
  }
}

/** Tailwind background+border+text badge classes for a letter grade. */
export function gradeBg(grade: string | null): string {
  switch (grade) {
    case 'A': return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30'
    case 'B': return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-500/10 dark:text-green-400 dark:border-green-500/30'
    case 'C': return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/30'
    case 'D': return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-400 dark:border-orange-500/30'
    case 'F': return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/30'
    default:  return 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/30'
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
