/**
 * Pure helper functions for dashboard UI logic.
 *
 * Style: domain value → Tone → token, expressed as declarative lookup maps
 * (no conditional chains). All functions are exported so they can be
 * unit-tested independently of the components that use them. Never hardcode
 * a semantic colour here — route through the Tone maps so light/dark parity
 * lives in one place (src/lib/design/sentiment.ts).
 */

import { SENTIMENT_TEXT, TONE_BADGE, TONE_DOT, TONE_TEXT, type Tone } from '@/lib/design/sentiment'
import { TRADE_FEED_EMPTY_LABELS, UI_COPY } from '@/constants/copy'

// ---------------------------------------------------------------------------
// Tone lookup tables — the single mapping from domain vocabulary to Tone
// ---------------------------------------------------------------------------

const ACTION_TONES: Record<string, Tone> = {
  BUY: 'success',
  SELL: 'danger',
}

const AGENT_STATUS_TONES: Record<string, Tone> = {
  Live: 'success',
  Stale: 'warning',
  Error: 'danger',
}

const SYSTEM_STATUS_TONES: Record<string, Tone> = {
  trading: 'success',
  booting: 'warning',
  error: 'danger',
}

const API_HEALTH_TONES: Record<string, Tone> = {
  ok: 'success',
  error: 'danger',
}

const PROPOSAL_STATUS_TONES: Record<string, Tone> = {
  approved: 'success',
  rejected: 'danger',
}

const ACTIVITY_INDICATOR_TONES: Record<string, Tone> = {
  live: 'success',
  waiting: 'warning',
}

// ---------------------------------------------------------------------------
// CSS class helpers — Trading / Positions
// ---------------------------------------------------------------------------

export function pnlColorClass(value: number): string {
  return value >= 0 ? SENTIMENT_TEXT.positive : SENTIMENT_TEXT.negative
}

/** Confidence is a continuous score — thresholds, not vocabulary, pick the Tone. */
export function confColorClass(conf: number | null): string {
  if (conf == null) return TONE_TEXT.neutral
  if (conf > 0.8) return TONE_TEXT.success
  if (conf >= 0.5) return TONE_TEXT.warning
  return TONE_TEXT.neutral
}

export function actionBadgeClass(action: string): string {
  return TONE_BADGE[ACTION_TONES[action] ?? 'neutral']
}

/** Text colour for a trade action/side (`buy`/`sell`, any case). */
export function actionTextClass(action: string): string {
  return TONE_TEXT[ACTION_TONES[action.toUpperCase()] ?? 'neutral']
}

/** Tone for a trade action/side — for `<Badge tone={…}>` call sites. */
export function toneForAction(action: string): Tone {
  return ACTION_TONES[action.toUpperCase()] ?? 'neutral'
}

/** 0–1 score → Meter fill colour: ≥0.8 success, ≥0.5 warning, else danger. */
export function meterFillClass(value: number): string {
  if (value >= 0.8) return TONE_DOT.success
  if (value >= 0.5) return TONE_DOT.warning
  return TONE_DOT.danger
}

/** 0–100 grade/score → text colour: ≥70 success, ≥40 warning, else danger. */
export function scoreColorClass(score: number | null): string {
  if (score == null) return TONE_TEXT.neutral
  if (score >= 70) return TONE_TEXT.success
  if (score >= 40) return TONE_TEXT.warning
  return TONE_TEXT.danger
}

// ---------------------------------------------------------------------------
// CSS class helpers — Agent activity
// ---------------------------------------------------------------------------

export function activityDotClass(indicator: string): string {
  const tone = ACTIVITY_INDICATOR_TONES[indicator] ?? 'neutral'
  return tone === 'success' ? `animate-pulse ${TONE_DOT.success}` : TONE_DOT[tone]
}

export function activityLabel(indicator: string): string {
  return UI_COPY.activityIndicator[indicator as keyof typeof UI_COPY.activityIndicator] ?? UI_COPY.activityIndicator.offline
}

// ---------------------------------------------------------------------------
// Value helpers — Trade feed
// ---------------------------------------------------------------------------

export function tradeFeedEmptyLabel(reason: string | null): string {
  return (reason && TRADE_FEED_EMPTY_LABELS[reason]) || TRADE_FEED_EMPTY_LABELS.default
}

// ---------------------------------------------------------------------------
// CSS class helpers — Agent status / System status
// ---------------------------------------------------------------------------

export function agentStatusDotClass(status: string): string {
  return TONE_DOT[AGENT_STATUS_TONES[status] ?? 'neutral']
}

export function systemStatusBadgeClass(status: string): string {
  return TONE_BADGE[SYSTEM_STATUS_TONES[status] ?? 'neutral']
}

export function apiHealthBadgeClass(value: string): string {
  return TONE_BADGE[API_HEALTH_TONES[value] ?? 'neutral']
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

const AGENT_TIERS: Record<string, 'active' | 'challenger' | 'inactive'> = {
  Live: 'active',
  Error: 'inactive',
}

export function agentTierFromStatus(status: string): 'active' | 'challenger' | 'inactive' {
  return AGENT_TIERS[status] ?? 'challenger'
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
  return TONE_BADGE[proposalStatusTone(status)]
}

/** Tone for a proposal review status — for `<Badge tone={…}>` call sites. */
export function proposalStatusTone(status: string | null | undefined): Tone {
  return (status && PROPOSAL_STATUS_TONES[status]) || 'warning'
}
