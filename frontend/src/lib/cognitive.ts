// Pure helpers + fetchers for the Cognitive dashboard.

import { apiFetch } from '@/lib/apiClient'
import type { CognitiveEvent, CognitiveSnapshot } from '@/types/cognitive'

export const fetchCognitiveState = (): Promise<CognitiveSnapshot> =>
  apiFetch<CognitiveSnapshot>('/cognitive/state')

export const fetchCognitiveEvents = (limit = 200): Promise<CognitiveEvent[]> =>
  apiFetch<CognitiveEvent[]>(`/cognitive/events?limit=${limit}`)

/** Tailwind tone classes for a letter grade (A/B/C/D/F, +/- modifiers, NR). */
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
      return 'bg-slate-500/10 text-slate-500 dark:text-slate-400 border-slate-500/20'
  }
}

/** Tailwind tone classes for a BUY / SELL / HOLD action. */
export function actionTone(action: string | null | undefined): string {
  switch ((action ?? '').toLowerCase()) {
    case 'buy':
      return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
    case 'sell':
      return 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30'
    default:
      return 'bg-slate-500/10 text-slate-500 dark:text-slate-400 border-slate-500/20'
  }
}

/** Tailwind tone classes for a proposal-lifecycle status. */
export function statusTone(status: string | null | undefined): string {
  switch ((status ?? '').toLowerCase()) {
    case 'approved':
    case 'merged':
      return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
    case 'rejected':
      return 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30'
    case 'backtesting':
    case 'awaiting_review':
      return 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
    default:
      return 'bg-slate-500/10 text-slate-500 dark:text-slate-400 border-slate-500/20'
  }
}

/** Signed, fixed-precision number for delta displays (e.g. "+0.18"). */
export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}
