/**
 * Contract tests for shared formatting helpers in src/lib/formatters.ts.
 */
import { describe, it, expect } from 'vitest'
import { formatUSD, signedUSD, formatTimeAgo, toFiniteNum } from '@/lib/formatters'

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

describe('formatTimeAgo', () => {
  it('returns empty string for null', () => {
    expect(formatTimeAgo(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(formatTimeAgo(undefined)).toBe('')
  })

  it('returns empty string for invalid string', () => {
    expect(formatTimeAgo('not-a-date')).toBe('')
  })

  it('handles a recent timestamp as seconds', () => {
    const ts = new Date(Date.now() - 30_000).toISOString()
    expect(formatTimeAgo(ts)).toBe('30s ago')
  })

  it('handles a Date object', () => {
    const d = new Date(Date.now() - 90_000)
    expect(formatTimeAgo(d)).toBe('1m ago')
  })
})

describe('toFiniteNum', () => {
  it('returns null for null', () => expect(toFiniteNum(null)).toBeNull())
  it('returns null for undefined', () => expect(toFiniteNum(undefined)).toBeNull())
  it('returns null for NaN', () => expect(toFiniteNum(NaN)).toBeNull())
  it('returns null for Infinity', () => expect(toFiniteNum(Infinity)).toBeNull())
  it('returns null for empty string', () => expect(toFiniteNum('')).toBeNull())
  it('converts a numeric string', () => expect(toFiniteNum('42.5')).toBe(42.5))
  it('passes through a finite number', () => expect(toFiniteNum(7)).toBe(7))
  it('returns null for non-numeric string', () => expect(toFiniteNum('abc')).toBeNull())
})
