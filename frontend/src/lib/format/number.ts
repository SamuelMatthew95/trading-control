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
