import { describe, expect, it } from 'vitest'
import { MISSING, formatCurrency, formatPercent, formatSignedCurrency, parseTimestamp, toFiniteNumber } from '@/lib/formatters'

describe('formatters', () => {
  it('formats currency and missing values safely', () => {
    expect(formatCurrency(12.3)).toBe('$12.30')
    expect(formatCurrency(-12.3)).toBe('$12.30')
    expect(formatCurrency(undefined)).toBe(MISSING)
  })

  it('formats signed currency without negative zero', () => {
    expect(formatSignedCurrency(10)).toBe('+$10.00')
    expect(formatSignedCurrency(-10)).toBe('-$10.00')
    expect(formatSignedCurrency(-0.0001)).toBe('$0.00')
  })

  it('parses finite numbers from strings', () => {
    expect(toFiniteNumber('42.5')).toBe(42.5)
    expect(toFiniteNumber('x')).toBeNull()
  })

  it('formats percent and parses timestamps', () => {
    expect(formatPercent(12.345, 1)).toBe('12.3%')
    expect(parseTimestamp('2026-01-01T00:00:00Z')?.toISOString()).toBe('2026-01-01T00:00:00.000Z')
  })
})
