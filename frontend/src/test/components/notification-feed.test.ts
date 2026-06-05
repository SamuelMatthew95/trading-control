import { describe, it, expect } from 'vitest'

import { formatRelativeTime } from '@/components/dashboard/NotificationFeed'

describe('NotificationFeed formatRelativeTime', () => {
  it('renders a float epoch-seconds string as relative time, not the raw value', () => {
    // Regression: "1780634112.7714157" rendered verbatim in the panel header and
    // rows because Date.parse could not read a float epoch-seconds string.
    const thirtySecondsAgoEpochSeconds = String((Date.now() - 30_000) / 1000)
    expect(formatRelativeTime(thirtySecondsAgoEpochSeconds)).toBe('30s ago')
  })

  it('handles epoch-ms numbers and ISO strings', () => {
    expect(formatRelativeTime(Date.now() - 90_000)).toBe('1m ago')
    expect(formatRelativeTime(new Date(Date.now() - 2 * 3_600_000).toISOString())).toBe('2h ago')
  })

  it('falls back to -- for missing or unparseable values (never the raw string)', () => {
    expect(formatRelativeTime(null)).toBe('--')
    expect(formatRelativeTime(undefined)).toBe('--')
    expect(formatRelativeTime('')).toBe('--')
    expect(formatRelativeTime('not-a-date')).toBe('--')
  })
})
