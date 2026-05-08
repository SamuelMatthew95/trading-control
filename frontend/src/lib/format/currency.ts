/**
 * Currency formatting primitives.
 *
 * Rules:
 * - Missing values → "—" (never "$0.00", never "NaN", never "$undefined")
 * - Zero / near-zero → "$0.00" (no leading sign, no "-$0.00" artifact)
 * - Positive signed → "+$X"
 * - Negative signed → "-$X"
 * - Large values (≥ 1000) get thousands separators with no decimals
 * - Small values keep two decimals
 */

import { MISSING, toFiniteNumber } from './number'

const ZERO_EPSILON = 0.005

function formatAbsolute(abs: number): string {
  if (abs >= 1000) {
    return abs.toLocaleString('en-US', { maximumFractionDigits: 0 })
  }
  return abs.toFixed(2)
}

/** Unsigned currency. Always positive — use `formatSignedCurrency` for P&L. */
export function formatCurrency(value: number | null | undefined): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  return `$${formatAbsolute(Math.abs(n))}`
}

/**
 * Signed currency for P&L / deltas.
 * - Positive: "+$123.45"
 * - Negative: "-$123.45"
 * - Zero (or near-zero rounding): "$0.00" (no sign — never "-$0.00")
 * - Missing: "—"
 */
export function formatSignedCurrency(value: number | null | undefined): string {
  const n = toFiniteNumber(value)
  if (n == null) return MISSING
  const abs = Math.abs(n)
  if (abs < ZERO_EPSILON) return '$0.00'
  const sign = n > 0 ? '+' : '-'
  return `${sign}$${formatAbsolute(abs)}`
}

/** Alias for trade P&L — clarifies intent at call sites. */
export const formatPnl = formatSignedCurrency

/** Price display — fixed two decimals, no thousands separator unless ≥ 1000. */
export function formatPrice(value: number | null | undefined): string {
  return formatCurrency(value)
}
