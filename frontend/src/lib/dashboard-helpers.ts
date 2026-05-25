/**
 * Pure helper functions for dashboard UI logic.
 *
 * All functions here are exported so they can be unit-tested independently
 * of the components that use them. CSS class helpers return Tailwind class
 * strings; value helpers return formatted display strings or computed numbers.
 */

// ---------------------------------------------------------------------------
// CSS class helpers — Trading / Positions
// ---------------------------------------------------------------------------

export function pnlColorClass(value: number): string {
  return value >= 0
    ? 'text-emerald-600 dark:text-emerald-400'
    : 'text-rose-600 dark:text-rose-400'
}

export function tradeSideClass(side: string | null): string {
  return side === 'buy' ? 'text-emerald-500' : 'text-rose-500'
}

export function strategyStatusClass(status: string | null): string {
  if (status === 'approved') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400'
  if (status === 'rejected') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-400'
  return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400'
}

export function confColorClass(conf: number | null): string {
  if (conf == null) return 'text-slate-400'
  if (conf > 0.8) return 'text-emerald-500'
  if (conf >= 0.5) return 'text-amber-500'
  return 'text-slate-400'
}

export function actionBadgeClass(action: string): string {
  if (action === 'BUY') return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
  if (action === 'SELL') return 'bg-rose-500/15 text-rose-500'
  return 'bg-slate-500/10 text-slate-500'
}

export function positionSideBadgeClass(side: string): string {
  if (side === 'LONG') return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
  if (side === 'SHORT') return 'bg-rose-500/15 text-rose-500'
  return 'bg-slate-500/10 text-slate-500'
}

// ---------------------------------------------------------------------------
// CSS class helpers — Agent activity
// ---------------------------------------------------------------------------

export function activityDotClass(indicator: string): string {
  if (indicator === 'live') return 'animate-pulse bg-emerald-500'
  if (indicator === 'waiting') return 'bg-amber-400'
  return 'bg-slate-400'
}

export function activityLabel(indicator: string): string {
  if (indicator === 'live') return 'LIVE'
  if (indicator === 'waiting') return 'WAITING'
  return 'OFFLINE'
}

// ---------------------------------------------------------------------------
// Value helpers — Trade feed
// ---------------------------------------------------------------------------

export function tradeFeedEmptyLabel(reason: string | null): string {
  if (reason === 'db_degraded') return 'DB unavailable — fills will appear when DB reconnects'
  if (reason === 'no_orders_executed') return 'No orders executed yet — decisions are being evaluated'
  if (reason === 'lifecycle_not_persisted') return 'Orders placed but lifecycle rows are pending'
  if (reason === 'no_executable_intents') return 'Pipeline active — no executable intents yet'
  return 'No fills yet — waiting for executed trades'
}

// ---------------------------------------------------------------------------
// Computation helpers
// ---------------------------------------------------------------------------

export function winRateFromFeed(feed: { pnl?: number | null }[]): number | null {
  const withPnl = feed.filter((t) => t.pnl != null)
  if (withPnl.length === 0) return null
  return (withPnl.filter((t) => (t.pnl ?? 0) > 0).length / withPnl.length) * 100
}
