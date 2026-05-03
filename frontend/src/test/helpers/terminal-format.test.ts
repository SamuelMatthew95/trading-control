import { formatCurrency, formatPercent, formatSignedCurrency, formatSignedPercent, MISSING_VALUE } from '@/lib/format/terminal'

describe('terminal format utils', () => {
  test('handles missing values', () => {
    expect(formatCurrency(undefined)).toBe(MISSING_VALUE)
    expect(formatPercent(null)).toBe(MISSING_VALUE)
  })

  test('formats signed currency and percent', () => {
    expect(formatSignedCurrency(12.34)).toBe('+$12.34')
    expect(formatSignedCurrency(-12.34)).toBe('-$12.34')
    expect(formatSignedPercent(2.5, 1)).toBe('+2.5%')
    expect(formatSignedPercent(-2.5, 1)).toBe('-2.5%')
  })
})
