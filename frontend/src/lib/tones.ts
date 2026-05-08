export type Tone = 'pos' | 'neg' | 'warn' | 'info' | 'muted'

export const TONE_CLASSES: Record<Tone, string> = {
  pos: 'text-emerald-600 dark:text-emerald-400',
  neg: 'text-rose-600 dark:text-rose-400',
  warn: 'text-amber-600 dark:text-amber-400',
  info: 'text-sky-600 dark:text-sky-400',
  muted: 'text-slate-500 dark:text-slate-400',
}

export const toneForTradeSide = (side: string | null | undefined): Tone => {
  if (!side) return 'muted'
  const normalized = side.toLowerCase()
  if (normalized === 'buy' || normalized === 'long') return 'pos'
  if (normalized === 'sell' || normalized === 'short') return 'neg'
  return 'muted'
}
