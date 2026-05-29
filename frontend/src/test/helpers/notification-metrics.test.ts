import { describe, it, expect } from 'vitest'

import { countRecentNotifications, lastNotificationLabel } from '@/lib/notification-metrics'

const HOUR_MS = 3_600_000

describe('countRecentNotifications', () => {
  it('counts only notifications within the window, not the full stored backlog', () => {
    const now = Date.now()
    const recent = new Date(now - 60_000).toISOString() // 1 minute ago
    const old = new Date(now - 5 * HOUR_MS).toISOString() // 5 hours ago
    const notifications = [{ timestamp: recent }, { timestamp: old }, { timestamp: old }]
    // Stored backlog is 3, but only 1 is recent — the headline must be 1, not 3.
    expect(countRecentNotifications(notifications, HOUR_MS)).toBe(1)
  })

  it('ignores unparseable or missing timestamps', () => {
    expect(countRecentNotifications([{ timestamp: 'not-a-date' }, {}], HOUR_MS)).toBe(0)
  })

  it('returns 0 for an empty list', () => {
    expect(countRecentNotifications([], HOUR_MS)).toBe(0)
  })
})

describe('lastNotificationLabel', () => {
  it('returns a no-activity placeholder when the latest timestamp is invalid or absent', () => {
    expect(lastNotificationLabel([{ timestamp: 'not-a-date' }])).toBe('No activity yet')
    expect(lastNotificationLabel([])).toBe('No activity yet')
  })

  it('labels the newest valid timestamp', () => {
    expect(lastNotificationLabel([{ timestamp: new Date().toISOString() }])).toMatch(/^Last: /)
  })
})
