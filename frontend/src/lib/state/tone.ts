/**
 * Semantic tone system — the SINGLE source of truth for status colors.
 *
 * Color always means state. Never use raw color names in components — pick a
 * tone and look up the classes here. Adding a new visual treatment? Add a tone
 * here and use it everywhere.
 *
 * Tones:
 *   pos   — positive / live / active / approved / buy
 *   neg   — negative / error / rejected / sell / loss
 *   warn  — warning / stale / degraded / pending
 *   info  — informational / unknown
 *   muted — idle / no data / inactive
 */

export type Tone = 'pos' | 'neg' | 'warn' | 'info' | 'muted'

interface ToneClasses {
  /** Solid text color. */
  text: string
  /** Solid background swatch (used for dots, fills, indicators). */
  bg: string
  /** Border color. */
  border: string
  /** Soft background tint for chips / cards (text-tone over tinted bg). */
  soft: string
  /** Compact chip className (border + soft bg + text). */
  chip: string
  /** Card-style border + soft tint. */
  card: string
}

export const TONE_CLASSES: Record<Tone, ToneClasses> = {
  pos: {
    text: 'text-emerald-500',
    bg: 'bg-emerald-500',
    border: 'border-emerald-500/40',
    soft: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    chip: 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    card: 'border border-emerald-500/30 bg-emerald-500/5',
  },
  neg: {
    text: 'text-rose-500',
    bg: 'bg-rose-500',
    border: 'border-rose-500/40',
    soft: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
    chip: 'border border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400',
    card: 'border border-rose-500/30 bg-rose-500/5',
  },
  warn: {
    text: 'text-amber-500',
    bg: 'bg-amber-500',
    border: 'border-amber-500/40',
    soft: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
    chip: 'border border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
    card: 'border border-amber-500/30 bg-amber-500/5',
  },
  info: {
    text: 'text-slate-500',
    bg: 'bg-slate-500',
    border: 'border-slate-500/40',
    soft: 'bg-slate-500/10 text-slate-600 dark:text-slate-300',
    chip: 'border border-slate-500/30 bg-slate-500/10 text-slate-600 dark:text-slate-300',
    card: 'border border-slate-200 dark:border-slate-800',
  },
  muted: {
    text: 'text-slate-400',
    bg: 'bg-slate-400',
    border: 'border-slate-400/40',
    soft: 'bg-transparent text-slate-400',
    chip: 'border border-slate-400/30 bg-transparent text-slate-400',
    card: 'border border-slate-200 dark:border-slate-800',
  },
}

/** Numeric sign → tone. Positive = pos, negative = neg, zero/null = muted. */
export function getNumberTone(value: number | null | undefined): Tone {
  if (value == null || !Number.isFinite(value)) return 'muted'
  if (value > 0) return 'pos'
  if (value < 0) return 'neg'
  return 'muted'
}
