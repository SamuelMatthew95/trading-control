export const STATE_TONE: Record<string, string> = {
  active: 'bg-emerald-500/10 text-emerald-600',
  live: 'bg-emerald-500/10 text-emerald-600',
  idle: 'bg-slate-500/10 text-slate-500',
  waiting: 'bg-amber-500/10 text-amber-600',
  pending: 'bg-amber-500/10 text-amber-600',
  error: 'bg-rose-500/10 text-rose-600',
  degraded: 'bg-amber-500/10 text-amber-600',
  offline: 'bg-slate-500/10 text-slate-500',
  open: 'bg-emerald-500/10 text-emerald-600',
  closed: 'bg-slate-500/10 text-slate-500',
  filled: 'bg-emerald-500/10 text-emerald-600',
  rejected: 'bg-rose-500/10 text-rose-600',
  buy: 'bg-emerald-500/10 text-emerald-600',
  sell: 'bg-rose-500/10 text-rose-600',
}

export const UNKNOWN_TONE = 'bg-slate-500/10 text-slate-500'

export function getStateTone(state: string): string {
  return STATE_TONE[state.toLowerCase()] ?? UNKNOWN_TONE
}

export function getStateLabel(state: string): string {
  const v = state.trim()
  return v ? v.toUpperCase() : 'UNKNOWN'
}

export function getPnlTone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return UNKNOWN_TONE
  if (value > 0) return STATE_TONE.buy
  if (value < 0) return STATE_TONE.sell
  return UNKNOWN_TONE
}

export function getTradeSideTone(side: string): string {
  return getStateTone(side)
}
