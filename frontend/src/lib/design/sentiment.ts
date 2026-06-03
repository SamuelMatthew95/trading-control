/**
 * Sentiment — the design system's semantic model for whether a value reads as
 * good, bad, or neutral, decoupled from colour.
 *
 * Keep these three concerns separate. A component must never map a raw number
 * straight to a Tailwind class:
 *
 *   1. business meaning   value      → Sentiment       (sentimentOf)
 *   2. design tokens      Sentiment  → class string    (SENTIMENT_TEXT)
 *   3. convenience        value      → class string     (sentimentTextClass)
 *
 * This is the single source of truth for the app's "green for up / red for
 * down / grey for flat" colour language — change the palette here and every
 * surface (and both light + dark themes) updates in lock-step.
 */

export type Sentiment = 'positive' | 'negative' | 'neutral'

/**
 * Dead-band below which a signed score is treated as neutral rather than
 * positive or negative. Prevents rounding-noise (e.g. an alpha of 1e-9) from
 * flickering green/red, and is defined exactly once so every signed-value →
 * Sentiment mapping shares the same threshold.
 */
export const SENTIMENT_EPSILON = 0.001

/** Map a signed value to a Sentiment. null / NaN / within the dead-band → neutral. */
export function sentimentOf(value: number | null | undefined): Sentiment {
  if (value == null || !Number.isFinite(value)) return 'neutral'
  if (value > SENTIMENT_EPSILON) return 'positive'
  if (value < -SENTIMENT_EPSILON) return 'negative'
  return 'neutral'
}

/**
 * Canonical text colour per sentiment — the single source of truth. Every
 * directional text colour in the app resolves through this map.
 */
export const SENTIMENT_TEXT: Record<Sentiment, string> = {
  positive: 'text-emerald-600 dark:text-emerald-400',
  negative: 'text-rose-600 dark:text-rose-400',
  neutral: 'text-slate-500 dark:text-slate-400',
}

/** Convenience composer: signed value → canonical sentiment text colour. */
export function sentimentTextClass(value: number | null | undefined): string {
  return SENTIMENT_TEXT[sentimentOf(value)]
}
