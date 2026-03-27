import { describe, it, expect } from 'vitest'

const sanitizeValue = (value: any): string => {
  if (value === undefined || value === null || value === '') return '--'
  if (typeof value === 'number' && (isNaN(value) || !isFinite(value))) return '--'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return String(value)
}

const formatUSD = (value?: number | null): string => {
  if (value == null || isNaN(value) || !isFinite(value)) return '$0.00'
  return `$${Math.abs(value).toFixed(2)}`
}

describe('sanitizeValue', () => {
  it('returns -- for undefined', () => expect(sanitizeValue(undefined)).toBe('--'))
  it('returns -- for null', () => expect(sanitizeValue(null)).toBe('--'))
  it('returns -- for empty string', () => expect(sanitizeValue('')).toBe('--'))
  it('returns -- for NaN', () => expect(sanitizeValue(NaN)).toBe('--'))
  it('returns -- for Infinity', () => expect(sanitizeValue(Infinity)).toBe('--'))
  it('returns -- for negative Infinity', () => expect(sanitizeValue(-Infinity)).toBe('--'))
  it('returns string for valid number', () => expect(sanitizeValue(42)).toBe('42'))
  it('returns string for zero', () => expect(sanitizeValue(0)).toBe('0'))
  it('returns string for negative number', () => expect(sanitizeValue(-100)).toBe('-100'))
  it('returns True for boolean true', () => expect(sanitizeValue(true)).toBe('True'))
  it('returns False for boolean false', () => expect(sanitizeValue(false)).toBe('False'))
  it('passes through valid strings', () => expect(sanitizeValue('hello')).toBe('hello'))
})

describe('formatUSD', () => {
  it('returns $0.00 for undefined', () => expect(formatUSD(undefined)).toBe('$0.00'))
  it('returns $0.00 for null', () => expect(formatUSD(null)).toBe('$0.00'))
  it('returns $0.00 for NaN', () => expect(formatUSD(NaN)).toBe('$0.00'))
  it('returns $0.00 for Infinity', () => expect(formatUSD(Infinity)).toBe('$0.00'))
  it('formats positive number', () => expect(formatUSD(1234.56)).toBe('$1234.56'))
  it('formats zero', () => expect(formatUSD(0)).toBe('$0.00'))
  it('formats negative as positive absolute', () => expect(formatUSD(-500)).toBe('$500.00'))
  it('rounds to 2 decimal places', () => expect(formatUSD(1.999)).toBe('$2.00'))
})
