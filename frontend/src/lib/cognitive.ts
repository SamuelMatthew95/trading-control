// Pure helpers + fetchers for the Cognitive dashboard.

import { apiFetch } from '@/lib/apiClient'
import { NO_DATA } from '@/constants/copy'
import { TONE_BADGE_OUTLINED } from '@/lib/design/sentiment'
import type { CognitiveEvent, CognitiveSnapshot, DecisionPayload } from '@/types/cognitive'

// Backend payload keys read off loosely-typed snapshot sub-objects (the live
// adapter returns `Record<string, unknown>` for trace outcomes / live-agent
// facets). Named here so no raw key string is sprinkled through the panels.
export const FIELD_REALIZED_PNL_PCT = 'realized_pnl_pct'
export const FIELD_TYPE = 'type'
/** Legacy sim roster suffix (`news_signal` → `news`); harmless no-op for live. */
export const EMITS_SIGNAL_SUFFIX = '_signal'

export const fetchCognitiveState = (): Promise<CognitiveSnapshot> =>
  apiFetch<CognitiveSnapshot>('/cognitive/state')

export const fetchCognitiveEvents = (limit = 200): Promise<CognitiveEvent[]> =>
  apiFetch<CognitiveEvent[]>(`/cognitive/events?limit=${limit}`)

/** Outlined chip classes for a BUY / SELL / HOLD action. */
export function actionTone(action: string | null | undefined): string {
  switch ((action ?? '').toLowerCase()) {
    case 'buy':
      return TONE_BADGE_OUTLINED.success
    case 'sell':
      return TONE_BADGE_OUTLINED.danger
    default:
      return TONE_BADGE_OUTLINED.neutral
  }
}

/** Outlined chip classes for a proposal-lifecycle status. */
export function statusTone(status: string | null | undefined): string {
  switch ((status ?? '').toLowerCase()) {
    case 'approved':
    case 'merged':
      return TONE_BADGE_OUTLINED.success
    case 'rejected':
      return TONE_BADGE_OUTLINED.danger
    case 'backtesting':
    case 'awaiting_review':
      return TONE_BADGE_OUTLINED.warning
    default:
      return TONE_BADGE_OUTLINED.neutral
  }
}

/** Signed, fixed-precision number for delta displays (e.g. "+0.18"). */
export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return NO_DATA
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

export interface DecisionStats {
  total: number
  buys: number
  sells: number
  holds: number
  /** Decisions where the reasoning LLM actually ran. */
  llmRan: number
  /** Decisions that fell back to rule-based logic (LLM unavailable). */
  fallbacks: number
  /** Share of decisions whose LLM call succeeded (0..1), or null if unknown. */
  successRate: number | null
  /** Mean decision confidence across the window (0..1). */
  avgConfidence: number
}

/** A decision is a rule-based fallback when the reasoning LLM could not run. */
export function isFallbackDecision(d: DecisionPayload): boolean {
  if (d.llm_succeeded === false) return true
  return (d.reasoning_summary ?? '').startsWith('fallback:')
}

/** Aggregate the live decision window into the Command Center's headline stats. */
export function summarizeDecisions(decisions: DecisionPayload[]): DecisionStats {
  let buys = 0
  let sells = 0
  let holds = 0
  let llmRan = 0
  let known = 0
  let confSum = 0
  for (const d of decisions) {
    const action = (d.action ?? '').toLowerCase()
    // Only buy/sell move a position; everything else (hold, and the fail-closed
    // `reject` the agent emits when the LLM is down) is a no-trade → holds.
    // The rule-based count below surfaces LLM-down rejects separately.
    if (action === 'buy') buys += 1
    else if (action === 'sell') sells += 1
    else holds += 1
    if (d.llm_succeeded != null) {
      known += 1
      if (d.llm_succeeded) llmRan += 1
    }
    confSum += typeof d.confidence === 'number' ? d.confidence : d.score ?? 0
  }
  const total = decisions.length
  return {
    total,
    buys,
    sells,
    holds,
    llmRan,
    fallbacks: known - llmRan,
    successRate: known > 0 ? llmRan / known : null,
    avgConfidence: total > 0 ? confSum / total : 0,
  }
}
