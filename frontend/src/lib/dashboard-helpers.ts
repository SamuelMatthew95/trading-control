/**
 * Pure helper functions for dashboard UI logic.
 *
 * All functions here are exported so they can be unit-tested independently
 * of the components that use them. CSS class helpers return Tailwind class
 * strings; value helpers return formatted display strings or computed numbers.
 */

import { SENTIMENT_TEXT, TONE_BADGE, TONE_DOT, TONE_TEXT, sentimentTextClass } from '@/lib/design/sentiment'

// ---------------------------------------------------------------------------
// CSS class helpers — Trading / Positions
// ---------------------------------------------------------------------------

export function pnlColorClass(value: number): string {
  return value >= 0 ? SENTIMENT_TEXT.positive : SENTIMENT_TEXT.negative
}

export function tradeSideClass(side: string | null): string {
  return side === 'buy' ? SENTIMENT_TEXT.positive : SENTIMENT_TEXT.negative
}

export function strategyStatusClass(status: string | null): string {
  if (status === 'approved') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400'
  if (status === 'rejected') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-400'
  return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400'
}

export function confColorClass(conf: number | null): string {
  if (conf == null) return TONE_TEXT.neutral
  if (conf > 0.8) return TONE_TEXT.success
  if (conf >= 0.5) return TONE_TEXT.warning
  return TONE_TEXT.neutral
}

export function actionBadgeClass(action: string): string {
  if (action === 'BUY') return TONE_BADGE.success
  if (action === 'SELL') return TONE_BADGE.danger
  return TONE_BADGE.neutral
}

export function positionSideBadgeClass(side: string): string {
  if (side === 'LONG') return TONE_BADGE.success
  if (side === 'SHORT') return TONE_BADGE.danger
  return TONE_BADGE.neutral
}

// ---------------------------------------------------------------------------
// CSS class helpers — Agent activity
// ---------------------------------------------------------------------------

export function activityDotClass(indicator: string): string {
  if (indicator === 'live') return `animate-pulse ${TONE_DOT.success}`
  if (indicator === 'waiting') return TONE_DOT.warning
  return TONE_DOT.neutral
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
// CSS class helpers — Agent card grid (DashboardView)
// ---------------------------------------------------------------------------

export function agentCardBorderClass(status: string): string {
  if (status === 'Live') return 'border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/20'
  if (status === 'Error') return 'border-rose-200 bg-rose-50/30 dark:border-rose-900/30 dark:bg-rose-950/10'
  return 'border-slate-200 dark:border-slate-800'
}

export function agentCardDotClass(status: string): string {
  if (status === 'Live') return `animate-pulse ${TONE_DOT.success}`
  if (status === 'Stale') return TONE_DOT.warning
  if (status === 'Error') return TONE_DOT.danger
  return TONE_DOT.neutral
}

export function agentCardTextClass(status: string): string {
  if (status === 'Live') return TONE_TEXT.success
  if (status === 'Stale') return TONE_TEXT.warning
  if (status === 'Error') return TONE_TEXT.danger
  return TONE_TEXT.neutral
}

// ---------------------------------------------------------------------------
// CSS class helpers — Stream events / System status
// ---------------------------------------------------------------------------

export function streamEventBadgeClass(stream: string | null | undefined): string {
  switch (stream) {
    case 'market_ticks':
    case 'market_events':
      return 'bg-emerald-500/20 text-emerald-400'
    case 'signals':
      return 'bg-sky-500/20 text-sky-400'
    case 'decisions':
      return 'bg-violet-500/20 text-violet-300'
    case 'orders':
      return 'bg-amber-500/20 text-amber-400'
    case 'executions':
      return 'bg-orange-500/20 text-orange-400'
    case 'risk_alerts':
      return 'bg-rose-500/20 text-rose-400'
    case 'notifications':
      return 'bg-blue-500/20 text-blue-400'
    case 'agent_logs':
      return 'bg-slate-400/20 text-slate-300'
    case 'system_metrics':
      return 'bg-indigo-500/20 text-indigo-400'
    case 'agent_grades':
    case 'graded_decisions':
      return 'bg-pink-500/20 text-pink-400'
    default:
      return 'bg-slate-500/20 text-slate-400'
  }
}

export function systemStatusBadgeClass(status: string): string {
  if (status === 'trading') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300'
  if (status === 'booting') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300'
  if (status === 'error') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300'
  return 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
}

// ---------------------------------------------------------------------------
// Computation helpers
// ---------------------------------------------------------------------------

export function winRateFromFeed(feed: { pnl?: number | null }[]): number | null {
  const withPnl = feed.filter((t) => t.pnl != null)
  if (withPnl.length === 0) return null
  return (withPnl.filter((t) => (t.pnl ?? 0) > 0).length / withPnl.length) * 100
}

// ---------------------------------------------------------------------------
// CSS class helpers — Agent status table (lighter palette than card grid)
// ---------------------------------------------------------------------------

export function agentStatusDotClass(status: string): string {
  if (status === 'Live') return 'bg-emerald-300'
  if (status === 'Stale') return 'bg-amber-300'
  if (status === 'Error') return 'bg-rose-300'
  return 'bg-slate-400'
}

export function pipelineStatusTextClass(status: string): string {
  if (status === 'Healthy') return TONE_TEXT.success
  if (status === 'Degraded') return TONE_TEXT.warning
  return TONE_TEXT.danger
}

export function apiHealthBadgeClass(value: string): string {
  if (value === 'ok') return TONE_BADGE.success
  if (value === 'error') return TONE_BADGE.danger
  return TONE_BADGE.neutral
}

export function priceChangeTextClass(change: number | null, hasData: boolean): string {
  if (change == null || !hasData) return SENTIMENT_TEXT.neutral
  return sentimentTextClass(change)
}

// ---------------------------------------------------------------------------
// Value helpers — Agent tier / Performance colour
// ---------------------------------------------------------------------------

export function agentTierFromStatus(status: string): 'active' | 'challenger' | 'inactive' {
  if (status === 'Live') return 'active'
  if (status === 'Error') return 'inactive'
  return 'challenger'
}

export function performancePnlColorClass(pnl: number | null): string {
  if (pnl == null) return 'text-slate-900 dark:text-slate-100'
  return pnl >= 0 ? SENTIMENT_TEXT.positive : SENTIMENT_TEXT.negative
}

// ---------------------------------------------------------------------------
// CSS class helpers — review-status badge (shared primitive)
// ---------------------------------------------------------------------------

/**
 * Badge classes for a proposal review status: approved = success, rejected =
 * danger, anything else (pending/null) = warning. One definition shared by the
 * proposals queue and the learning console.
 */
export function proposalStatusClass(status: string | null | undefined): string {
  if (status === 'approved') return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300'
  if (status === 'rejected') return 'border-rose-400/30 bg-rose-400/10 text-rose-700 dark:text-rose-300'
  return 'border-amber-400/30 bg-amber-400/10 text-amber-700 dark:text-amber-300'
}
