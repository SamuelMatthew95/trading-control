// Pure helpers + fetchers for the Cognitive dashboard.

import { apiFetch } from '@/lib/apiClient'
import { NO_DATA } from '@/constants/copy'
import { TONE_BADGE_OUTLINED } from '@/lib/design/sentiment'
import type { CognitiveEvent, CognitiveSnapshot } from '@/types/cognitive'

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
