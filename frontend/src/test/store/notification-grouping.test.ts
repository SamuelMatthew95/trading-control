import { describe, it, expect } from 'vitest'
import {
  groupNotifications,
  notificationGroupKey,
  isSystemInternalNotification,
  type GroupableNotification,
} from '@/lib/notification-grouping'

const make = (overrides: Partial<GroupableNotification> = {}): GroupableNotification => ({
  id: Math.random().toString(36).slice(2),
  notification_type: 'trade.buy_filled',
  symbol: 'BTC/USD',
  action: 'buy',
  title: 'BUY filled: BTC/USD',
  timestamp: new Date().toISOString(),
  severity: 'info',
  ...overrides,
})

describe('notificationGroupKey', () => {
  it('builds key from type + symbol + action', () => {
    const key = notificationGroupKey(make({ notification_type: 'trade.buy_filled', symbol: 'ETH/USD', action: 'buy' }))
    expect(key).toBe('trade.buy_filled|ETH/USD|buy')
  })

  it('falls back to empty string for missing fields', () => {
    const key = notificationGroupKey({ id: 'x' })
    expect(key).toBe('unknown||')
  })

  it('different symbols produce different keys', () => {
    const a = notificationGroupKey(make({ symbol: 'BTC/USD' }))
    const b = notificationGroupKey(make({ symbol: 'ETH/USD' }))
    expect(a).not.toBe(b)
  })

  it('different actions produce different keys', () => {
    const a = notificationGroupKey(make({ action: 'buy' }))
    const b = notificationGroupKey(make({ action: 'sell' }))
    expect(a).not.toBe(b)
  })
})

describe('groupNotifications', () => {
  it('returns empty array for empty input', () => {
    expect(groupNotifications([])).toEqual([])
  })

  it('returns single group for single notification', () => {
    const n = make()
    const groups = groupNotifications([n])
    expect(groups).toHaveLength(1)
    expect(groups[0].count).toBe(1)
    expect(groups[0].latest).toBe(n)
  })

  it('groups identical type+symbol+action into one group', () => {
    const older = make({ timestamp: '2026-01-01T10:00:00Z' })
    const newer = make({ timestamp: '2026-01-01T10:01:00Z' })
    const groups = groupNotifications([newer, older])
    expect(groups).toHaveLength(1)
    expect(groups[0].count).toBe(2)
    expect(groups[0].latest).toBe(newer)
  })

  it('keeps latest notification as representative', () => {
    const old = make({ id: 'old', timestamp: '2026-01-01T09:00:00Z' })
    const mid = make({ id: 'mid', timestamp: '2026-01-01T10:00:00Z' })
    const latest = make({ id: 'new', timestamp: '2026-01-01T11:00:00Z' })
    const groups = groupNotifications([old, latest, mid])
    expect(groups[0].latest.id).toBe('new')
    expect(groups[0].count).toBe(3)
  })

  it('separates notifications with different symbols', () => {
    const btc = make({ symbol: 'BTC/USD' })
    const eth = make({ symbol: 'ETH/USD' })
    const groups = groupNotifications([btc, eth])
    expect(groups).toHaveLength(2)
  })

  it('separates buy from sell', () => {
    const buy = make({ action: 'buy', notification_type: 'trade.buy_filled' })
    const sell = make({ action: 'sell', notification_type: 'trade.sell_filled' })
    const groups = groupNotifications([buy, sell])
    expect(groups).toHaveLength(2)
  })

  it('preserves first-occurrence order', () => {
    const first = make({ symbol: 'BTC/USD', timestamp: '2026-01-01T10:01:00Z' })
    const second = make({ symbol: 'ETH/USD', timestamp: '2026-01-01T10:00:00Z' })
    const firstDupe = make({ symbol: 'BTC/USD', timestamp: '2026-01-01T09:59:00Z' })
    const groups = groupNotifications([first, second, firstDupe])
    expect(groups[0].latest.symbol).toBe('BTC/USD')
    expect(groups[1].latest.symbol).toBe('ETH/USD')
  })

  it('respects maxGroups cap', () => {
    const ns = Array.from({ length: 10 }, (_, i) =>
      make({ symbol: `ASSET${i}/USD`, notification_type: 'trade.buy_filled', action: 'buy' }),
    )
    const groups = groupNotifications(ns, 3)
    expect(groups).toHaveLength(3)
  })

  it('count badge reflects number of duplicates', () => {
    const dupes = Array.from({ length: 5 }, () => make())
    const groups = groupNotifications(dupes)
    expect(groups).toHaveLength(1)
    expect(groups[0].count).toBe(5)
  })
})

describe('isSystemInternalNotification', () => {
  it('identifies system. prefix as internal', () => {
    expect(isSystemInternalNotification({ id: 'x', notification_type: 'system.startup' })).toBe(true)
    expect(isSystemInternalNotification({ id: 'x', notification_type: 'system.health_check' })).toBe(true)
  })

  it('identifies db_unavailable as internal', () => {
    expect(isSystemInternalNotification({ id: 'x', notification_type: 'db_unavailable' })).toBe(true)
  })

  it('identifies connection events as internal', () => {
    expect(isSystemInternalNotification({ id: 'x', notification_type: 'ws_connection_lost' })).toBe(true)
  })

  it('does not flag trade notifications as internal', () => {
    expect(isSystemInternalNotification({ id: 'x', notification_type: 'trade.buy_filled' })).toBe(false)
    expect(isSystemInternalNotification({ id: 'x', notification_type: 'trade.sell_filled' })).toBe(false)
  })

  it('handles missing type gracefully', () => {
    expect(isSystemInternalNotification({ id: 'x' })).toBe(false)
  })
})
