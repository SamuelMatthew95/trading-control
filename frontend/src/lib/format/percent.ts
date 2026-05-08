/**
 * Percent formatting primitives.
 *
 * IMPORTANT: convention here is that the input is already in PERCENT units
 * (i.e. 25 means 25%). Use `formatRatioAsPercent` if your input is a ratio
 * in [0, 1].
 */

import { MISSING, toFiniteNumber } from './number'

/** Unsigned percent — input is already in percent units (25 → "25.00%"). */
export function formatPercent(
  value: number | null | undefined,
  decimals = 2,
): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  return `${n.toFixed(decimals)}%`
}

/** Signed percent — input is already in percent units. Adds explicit "+" sign. */
export function formatSignedPercent(
  value: number | null | undefined,
  decimals = 2,
): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(decimals)}%`
}

/** Input is a ratio in [0, 1] — output rounded to integer percent (0.85 → "85%"). */
export function formatRatioAsPercent(
  value: number | null | undefined,
  decimals = 0,
): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  return `${(n * 100).toFixed(decimals)}%`
}
