/**
 * Contract tests for shared formatting helpers in src/lib/formatters.ts.
 */
import { describe, it, expect } from 'vitest'
import {
  formatUSD,
  signedUSD,
  formatTimeAgo,
  formatPercent,
  formatQuantity,
  positionCostBasis,
  positionMarketValue,
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

describe('formatQuantity', () => {
  it('returns -- for null / undefined / non-finite', () => {
    expect(formatQuantity(null)).toBe('--')
    expect(formatQuantity(undefined)).toBe('--')
    expect(formatQuantity(NaN)).toBe('--')
    expect(formatQuantity(Infinity)).toBe('--')
  })

  it('renders a tiny fractional-crypto qty readably instead of a raw float', () => {
    // The bug: 0.0001681861435210638 rendered verbatim in the positions table.
    expect(formatQuantity(0.0001681861435210638)).toBe('0.00016819')
  })

  it('trims trailing zeros and caps small values at 8 dp', () => {
    expect(formatQuantity(0.5)).toBe('0.5')
    expect(formatQuantity(0.001)).toBe('0.001')
  })

  it('uses up to 4 dp for whole/large quantities', () => {
    expect(formatQuantity(100)).toBe('100')
    expect(formatQuantity(12.3456789)).toBe('12.3457')
  })

  it('formats zero as 0', () => {
    expect(formatQuantity(0)).toBe('0')
  })
})

describe('positionCostBasis', () => {
  it('is entry price × absolute quantity (the cash put in)', () => {
    expect(positionCostBasis({ entry_price: 67079.29, quantity: 0.0001681861435210638 })).toBeCloseTo(11.28, 2)
  })

  it('uses absolute quantity so a short reports its opening notional', () => {
    expect(positionCostBasis({ entry_price: 100, quantity: -2 })).toBe(200)
  })

  it('reads the qty alias (paper-broker Redis state)', () => {
    expect(positionCostBasis({ entry_price: 10, qty: 3 })).toBe(30)
  })

  it('returns null when entry price is missing', () => {
    expect(positionCostBasis({ quantity: 1 })).toBeNull()
  })
})

describe('positionMarketValue', () => {
  it('is the live price × absolute quantity', () => {
    const pos = { symbol: 'BTC/USD', entry_price: 67079.29, current_price: 60781.58, quantity: 0.0001681861435210638 }
    expect(positionMarketValue(pos)).toBeCloseTo(10.22, 2)
  })

  it('prefers the live price stream over the stored current_price', () => {
    const pos = { symbol: 'BTC/USD', current_price: 100, quantity: 2 }
    const prices = { 'BTC/USD': { price: 150 } }
    expect(positionMarketValue(pos, prices)).toBe(300)
  })

  it('returns null when no price is available', () => {
    expect(positionMarketValue({ symbol: 'X', quantity: 1 })).toBeNull()
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
