/**
 * Contract tests for shared formatting helpers in src/lib/formatters.ts.
 */
import { describe, it, expect } from 'vitest'
import {
  formatUSD,
  signedUSD,
  formatTimeAgo,
  formatPercent,
  toFiniteNum,
  getField,
  getStr,
} from '@/lib/formatters'

describe('getField', () => {
  it('reads a present key', () => {
    expect(getField({ a: 1 }, 'a')).toBe(1)
  })
  it('returns undefined for a missing key', () => {
    expect(getField({ a: 1 }, 'b')).toBeUndefined()
  })
  it('is safe on null / array / primitive (the cast-replacement contract)', () => {
    expect(getField(null, 'a')).toBeUndefined()
    expect(getField(undefined, 'a')).toBeUndefined()
    expect(getField([1, 2], 'a')).toBeUndefined()
    expect(getField('str', 'a')).toBeUndefined()
    expect(getField(42, 'a')).toBeUndefined()
  })
})

describe('getStr', () => {
  it('coalesces the first present alias to a string', () => {
    expect(getStr({ agent: 'x' }, 'agent_name', 'agent', 'source')).toBe('x')
    expect(getStr({ source: 's' }, 'agent_name', 'agent', 'source')).toBe('s')
  })
  it('skips null / empty-string fields', () => {
    expect(getStr({ a: '', b: 'real' }, 'a', 'b')).toBe('real')
    expect(getStr({ a: null, b: 'real' }, 'a', 'b')).toBe('real')
  })
  it('returns "" when no alias is present or object is not an object', () => {
    expect(getStr({ x: 1 }, 'a', 'b')).toBe('')
    expect(getStr(null, 'a')).toBe('')
    expect(getStr([1], 'a')).toBe('')
  })
  it('stringifies non-string values', () => {
    expect(getStr({ n: 7 }, 'n')).toBe('7')
  })
})

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

describe('formatPercent', () => {
  it('returns -- for null / undefined / NaN / Infinity', () => {
    expect(formatPercent(null)).toBe('--')
    expect(formatPercent(undefined)).toBe('--')
    expect(formatPercent(NaN)).toBe('--')
    expect(formatPercent(Infinity)).toBe('--')
  })

  it('auto-scales a fractional ratio (|v| <= 1) to a percent', () => {
    expect(formatPercent(0.42)).toBe('42.0%')
    expect(formatPercent(1)).toBe('100.0%')
    expect(formatPercent(-0.5)).toBe('-50.0%')
  })

  it('passes through magnitudes already in percent (|v| > 1)', () => {
    expect(formatPercent(42)).toBe('42.0%')
    expect(formatPercent(1.5)).toBe('1.5%')
  })

  it('respects the decimals option', () => {
    expect(formatPercent(0.4267, { decimals: 0 })).toBe('43%')
    expect(formatPercent(0.4, { decimals: 2 })).toBe('40.00%')
  })

  it('prefixes non-negative values with + when signed', () => {
    expect(formatPercent(0.42, { signed: true })).toBe('+42.0%')
    expect(formatPercent(0, { signed: true })).toBe('+0.0%')
    expect(formatPercent(-0.42, { signed: true })).toBe('-42.0%')
  })

  it('coerces numeric strings via toFiniteNum', () => {
    expect(formatPercent('0.5')).toBe('50.0%')
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
