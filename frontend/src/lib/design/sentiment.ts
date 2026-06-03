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
 * Tone — the full semantic palette the UI maps state onto. `Sentiment` is the
 * directional subset (positive→success, negative→danger). Status and health
 * vocabularies resolve to a Tone; a Tone resolves to a design token here. The
 * tokens are defined once in src/styles/globals.css and flipped for dark mode
 * there, so the palette and light/dark parity live in a single place — no
 * per-usage `dark:` pairs.
 */
export type Tone = 'success' | 'danger' | 'warning' | 'neutral'

/** Canonical text colour per Tone — the single source of truth. */
export const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success',
  danger: 'text-danger',
  warning: 'text-warning',
  neutral: 'text-muted-foreground',
}

/** Canonical status-dot background per Tone. */
export const TONE_DOT: Record<Tone, string> = {
  success: 'bg-success',
  danger: 'bg-danger',
  warning: 'bg-warning',
  neutral: 'bg-muted-foreground',
}

/** Canonical badge/chip classes per Tone — translucent fill + matching text. */
export const TONE_BADGE: Record<Tone, string> = {
  success: 'bg-success/10 text-success',
  danger: 'bg-danger/10 text-danger',
  warning: 'bg-warning/10 text-warning',
  neutral: 'bg-muted-foreground/10 text-muted-foreground',
}

/** Directional text colour — the directional subset of {@link TONE_TEXT}. */
export const SENTIMENT_TEXT: Record<Sentiment, string> = {
  positive: TONE_TEXT.success,
  negative: TONE_TEXT.danger,
  neutral: TONE_TEXT.neutral,
}

/** Convenience composer: signed value → canonical sentiment text colour. */
export function sentimentTextClass(value: number | null | undefined): string {
  return SENTIMENT_TEXT[sentimentOf(value)]
}
