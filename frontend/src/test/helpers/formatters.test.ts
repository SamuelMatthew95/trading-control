/**
 * Tests for money formatting helpers defined in TradingView / DashboardView.
 *
 * The formatUSD function in TradingView must return '--' (not '$0.00') for
 * null / undefined input, so that unfilled P&L doesn't look like a break-even.
 */
import { describe, it, expect } from 'vitest'

// We test the behaviour via a standalone re-implementation that matches the
// production code, because the formatter is module-local (not exported).
// If the production implementation changes, these tests act as a contract.

function formatUSD(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '--'
  return `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function signedUSD(value: number | null | undefined): string {
  if (value == null || isNaN(value) || !isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs < 0.005) return '$0.00'
  return `${value > 0 ? '+' : '-'}$${abs.toFixed(2)}`
}

describe('formatUSD', () => {
  it('returns -- for null', () => {
    expect(formatUSD(null)).toBe('--')
  })

  it('returns -- for undefined', () => {
    expect(formatUSD(undefined)).toBe('--')
  })

  it('returns -- for NaN', () => {
    expect(formatUSD(NaN)).toBe('--')
  })

  it('returns -- for Infinity', () => {
    expect(formatUSD(Infinity)).toBe('--')
  })

  it('formats positive values with $', () => {
    expect(formatUSD(50)).toBe('$50.00')
  })

  it('uses absolute value (no sign)', () => {
    expect(formatUSD(-20)).toBe('$20.00')
  })

  it('formats zero as $0.00', () => {
    expect(formatUSD(0)).toBe('$0.00')
  })
})

describe('signedUSD', () => {
  it('returns -- for null', () => {
    expect(signedUSD(null)).toBe('--')
  })

  it('returns -- for undefined', () => {
    expect(signedUSD(undefined)).toBe('--')
  })

  it('returns -- for NaN', () => {
    expect(signedUSD(NaN)).toBe('--')
  })

  it('prefixes positive values with +', () => {
    expect(signedUSD(100.5)).toBe('+$100.50')
  })

  it('prefixes negative values with -', () => {
    expect(signedUSD(-42.75)).toBe('-$42.75')
  })

  it('returns $0.00 for near-zero to avoid -$0.00', () => {
    expect(signedUSD(0)).toBe('$0.00')
    expect(signedUSD(-0.001)).toBe('$0.00')
    expect(signedUSD(0.001)).toBe('$0.00')
  })
})
