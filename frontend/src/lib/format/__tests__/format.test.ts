import { describe, it, expect } from 'vitest'
import {
  MISSING,
  isFiniteNumber,
  toFiniteNumber,
  formatNumber,
  formatCurrency,
  formatSignedCurrency,
  formatPercent,
  formatSignedPercent,
  formatRatioAsPercent,
  formatTimeAgo,
  formatDuration,
  formatUptime,
  parseTimestamp,
  formatTimestamp,
} from '../index'

describe('isFiniteNumber', () => {
  it('accepts finite numbers', () => {
    expect(isFiniteNumber(0)).toBe(true)
    expect(isFiniteNumber(-1.5)).toBe(true)
    expect(isFiniteNumber(1e9)).toBe(true)
  })
  it('rejects non-finite or non-number', () => {
    expect(isFiniteNumber(NaN)).toBe(false)
    expect(isFiniteNumber(Infinity)).toBe(false)
    expect(isFiniteNumber(null)).toBe(false)
    expect(isFiniteNumber(undefined)).toBe(false)
    expect(isFiniteNumber('1')).toBe(false)
  })
})

describe('toFiniteNumber', () => {
  it('coerces numeric strings', () => {
    expect(toFiniteNumber('42')).toBe(42)
    expect(toFiniteNumber('-3.14')).toBe(-3.14)
  })
  it('rejects garbage', () => {
    expect(toFiniteNumber('abc')).toBeNull()
    expect(toFiniteNumber('')).toBeNull()
    expect(toFiniteNumber(null)).toBeNull()
    expect(toFiniteNumber(NaN)).toBeNull()
    expect(toFiniteNumber(Infinity)).toBeNull()
  })
})

describe('formatNumber', () => {
  it('formats integers with separators by default', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
  })
  it('respects decimals', () => {
    expect(formatNumber(3.14159, 2)).toBe('3.14')
  })
  it('returns missing placeholder for invalid input', () => {
    expect(formatNumber(null)).toBe(MISSING)
    expect(formatNumber(undefined)).toBe(MISSING)
    expect(formatNumber(NaN)).toBe(MISSING)
  })
})

describe('formatCurrency', () => {
  it('shows two decimals for small values', () => {
    expect(formatCurrency(12.5)).toBe('$12.50')
  })
  it('drops decimals for large values', () => {
    expect(formatCurrency(12345)).toBe('$12,345')
  })
  it('takes absolute value (caller handles sign via formatSignedCurrency)', () => {
    expect(formatCurrency(-5.25)).toBe('$5.25')
  })
  it('returns missing for null/undefined/NaN', () => {
    expect(formatCurrency(null)).toBe(MISSING)
    expect(formatCurrency(undefined)).toBe(MISSING)
    expect(formatCurrency(NaN)).toBe(MISSING)
  })
})

describe('formatSignedCurrency', () => {
  it('positive with leading +', () => {
    expect(formatSignedCurrency(5.25)).toBe('+$5.25')
  })
  it('negative with leading -', () => {
    expect(formatSignedCurrency(-5.25)).toBe('-$5.25')
  })
  it('renders zero as $0.00 (no sign, no -$0.00 artifact)', () => {
    expect(formatSignedCurrency(0)).toBe('$0.00')
    expect(formatSignedCurrency(0.001)).toBe('$0.00')
    expect(formatSignedCurrency(-0.001)).toBe('$0.00')
  })
  it('returns missing for missing data', () => {
    expect(formatSignedCurrency(null)).toBe(MISSING)
    expect(formatSignedCurrency(undefined)).toBe(MISSING)
    expect(formatSignedCurrency(NaN)).toBe(MISSING)
  })
  it('large negative values keep their sign', () => {
    expect(formatSignedCurrency(-12345)).toBe('-$12,345')
  })
})

describe('formatPercent', () => {
  it('formats with default 2 decimals', () => {
    expect(formatPercent(25)).toBe('25.00%')
  })
  it('handles zero', () => {
    expect(formatPercent(0)).toBe('0.00%')
  })
  it('returns missing for invalid input', () => {
    expect(formatPercent(null)).toBe(MISSING)
    expect(formatPercent(NaN)).toBe(MISSING)
  })
})

describe('formatSignedPercent', () => {
  it('positive with sign', () => {
    expect(formatSignedPercent(5)).toBe('+5.00%')
  })
  it('negative with sign', () => {
    expect(formatSignedPercent(-5)).toBe('-5.00%')
  })
  it('zero shown without sign', () => {
    expect(formatSignedPercent(0)).toBe('0.00%')
  })
})

describe('formatRatioAsPercent', () => {
  it('converts ratio to percent', () => {
    expect(formatRatioAsPercent(0.85)).toBe('85%')
  })
  it('handles 1', () => {
    expect(formatRatioAsPercent(1)).toBe('100%')
  })
  it('returns missing for null', () => {
    expect(formatRatioAsPercent(null)).toBe(MISSING)
  })
})

describe('parseTimestamp', () => {
  it('parses ISO strings', () => {
    const d = parseTimestamp('2026-05-03T10:00:00Z')
    expect(d).toBeInstanceOf(Date)
  })
  it('parses unix seconds', () => {
    const d = parseTimestamp(1700000000)
    expect(d?.getFullYear()).toBe(2023)
  })
  it('parses unix milliseconds', () => {
    const d = parseTimestamp(1700000000000)
    expect(d?.getFullYear()).toBe(2023)
  })
  it('returns null for garbage', () => {
    expect(parseTimestamp('not a date')).toBeNull()
    expect(parseTimestamp(null)).toBeNull()
    expect(parseTimestamp('')).toBeNull()
    expect(parseTimestamp('0')).toBeNull()
  })
})

describe('formatTimestamp', () => {
  it('returns missing for invalid', () => {
    expect(formatTimestamp(null)).toBe(MISSING)
    expect(formatTimestamp('garbage')).toBe(MISSING)
  })
  it('produces a string for valid input', () => {
    expect(typeof formatTimestamp('2026-05-03T10:00:00Z')).toBe('string')
  })
})

describe('formatTimeAgo', () => {
  const now = new Date('2026-05-03T12:00:00Z').getTime()

  it('seconds bucket', () => {
    const d = new Date(now - 5_000).toISOString()
    expect(formatTimeAgo(d, now)).toBe('5s ago')
  })
  it('minutes bucket', () => {
    const d = new Date(now - 5 * 60_000).toISOString()
    expect(formatTimeAgo(d, now)).toBe('5m ago')
  })
  it('hours bucket', () => {
    const d = new Date(now - 3 * 3600_000).toISOString()
    expect(formatTimeAgo(d, now)).toBe('3h ago')
  })
  it('days bucket', () => {
    const d = new Date(now - 2 * 24 * 3600_000).toISOString()
    expect(formatTimeAgo(d, now)).toBe('2d ago')
  })
  it('returns missing for null', () => {
    expect(formatTimeAgo(null, now)).toBe(MISSING)
  })
})

describe('formatDuration', () => {
  it('seconds', () => {
    expect(formatDuration(5_000)).toBe('5s')
  })
  it('minutes', () => {
    expect(formatDuration(5 * 60_000)).toBe('5m')
  })
  it('hours', () => {
    expect(formatDuration(2 * 3600_000)).toBe('2h')
  })
  it('missing for null', () => {
    expect(formatDuration(null)).toBe(MISSING)
    expect(formatDuration(-1)).toBe(MISSING)
  })
})

describe('formatUptime', () => {
  it('seconds only', () => {
    expect(formatUptime(45)).toBe('45s')
  })
  it('minutes only', () => {
    expect(formatUptime(120)).toBe('2m')
  })
  it('hours and minutes', () => {
    expect(formatUptime(3 * 3600 + 25 * 60)).toBe('3h 25m')
  })
  it('missing for null', () => {
    expect(formatUptime(null)).toBe(MISSING)
  })
})
