/**
 * Pure helper functions for dashboard UI logic.
 *
 * All functions here are exported so they can be unit-tested independently
 * of the components that use them. CSS class helpers resolve a domain value
 * to a design token (see src/lib/design/sentiment.ts) and return Tailwind
 * class strings; value helpers return formatted display strings or computed
 * numbers. Never hardcode a semantic colour here — route through the Tone
 * maps so light/dark parity stays in one place.
 */

import { SENTIMENT_TEXT, TONE_BADGE, TONE_DOT, TONE_TEXT } from '@/lib/design/sentiment'

// ---------------------------------------------------------------------------
// CSS class helpers — Trading / Positions
// ---------------------------------------------------------------------------

export function pnlColorClass(value: number): string {
  return value >= 0 ? SENTIMENT_TEXT.positive : SENTIMENT_TEXT.negative
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
// CSS class helpers — Agent status / System status
// ---------------------------------------------------------------------------

export function agentStatusDotClass(status: string): string {
  if (status === 'Live') return TONE_DOT.success
  if (status === 'Stale') return TONE_DOT.warning
  if (status === 'Error') return TONE_DOT.danger
  return TONE_DOT.neutral
}

export function systemStatusBadgeClass(status: string): string {
  if (status === 'trading') return TONE_BADGE.success
  if (status === 'booting') return TONE_BADGE.warning
  if (status === 'error') return TONE_BADGE.danger
  return TONE_BADGE.neutral
}

export function apiHealthBadgeClass(value: string): string {
  if (value === 'ok') return TONE_BADGE.success
  if (value === 'error') return TONE_BADGE.danger
  return TONE_BADGE.neutral
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
// Value helpers — Agent tier
// ---------------------------------------------------------------------------

export function agentTierFromStatus(status: string): 'active' | 'challenger' | 'inactive' {
  if (status === 'Live') return 'active'
  if (status === 'Error') return 'inactive'
  return 'challenger'
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
  if (status === 'approved') return TONE_BADGE.success
  if (status === 'rejected') return TONE_BADGE.danger
  return TONE_BADGE.warning
}
