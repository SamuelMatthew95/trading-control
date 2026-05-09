/**
 * Number formatting primitives for terminal-grade UI.
 *
 * All formatters return the missing-value placeholder ("—") for null/undefined,
 * NaN, or Infinity — never crash and never render "NaN" or "0" by default.
 */

export const MISSING = '—'

/** Returns true only for finite numbers — rejects NaN, Infinity, null, undefined, strings. */
export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** Coerces unknown into a finite number or null. Accepts numeric strings. */
export function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

/** Plain number with optional decimals. */
export function formatNumber(
  value: number | null | undefined,
  decimals = 0,
): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/** Compact form: 1.2K, 3.4M, 1.5B. */
export function formatCompactNumber(value: number | null | undefined): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  return n.toLocaleString('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  })
}

/**
 * Read a confidence value from a record and normalize it to a 0–1 ratio.
 *
 * Handles three real-world shapes the backend may emit:
 *   - { confidence: 0.73 }         ← canonical 0-1 ratio
 *   - { confidence: 73 }           ← legacy / pre-normalization 0-100
 *   - { confidence_score: 0.73 }   ← alternate field name (LearningDashboard, evals)
 *
 * Single source of truth so every component reads confidence the same way.
 * Values > 1 are treated as percentages and divided by 100.
 * Returns null for null / undefined / NaN / negative inputs so callers can
 * render a `—` placeholder consistently.
 */
export function extractConfidence(
  record: Record<string, unknown> | null | undefined,
): number | null {
  if (!record) return null
  const raw = record.confidence_score ?? record.confidence
  const n = toFiniteNumber(raw)
  if (n == null || n < 0) return null
  if (n > 1) {
    // Treat values up to 100 as percentages. Anything beyond is bogus.
    if (n > 100) return null
    return n / 100
  }
  return n
}
