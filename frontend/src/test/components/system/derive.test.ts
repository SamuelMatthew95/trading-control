import { describe, it, expect } from 'vitest'

import {
  SURFACED_DECISION_LIMIT,
  deriveAgentActivity,
  deriveDecisionFeed,
  formatAge,
  formatClock,
  normalizeAction,
  resolveHealthTone,
  timestampMs,
} from '@/components/dashboard/system/derive'
import { ALL_AGENT_NAMES } from '@/constants/agents'
import type { AgentHeartbeat, AgentLog, Notification, Order } from '@/stores/useDashboardStore'

describe('normalizeAction', () => {
  it('maps trading vocabulary onto the four decision actions', () => {
    expect(normalizeAction('buy')).toBe('BUY')
    expect(normalizeAction('LONG')).toBe('BUY')
    expect(normalizeAction('sell')).toBe('SELL')
    expect(normalizeAction('short')).toBe('SELL')
    expect(normalizeAction('exit')).toBe('SELL')
    expect(normalizeAction('skip')).toBe('SKIP')
  })

  it('falls back to HOLD for unknown or missing values', () => {
    expect(normalizeAction('mystery')).toBe('HOLD')
    expect(normalizeAction(null)).toBe('HOLD')
    expect(normalizeAction(undefined)).toBe('HOLD')
  })
})

describe('timestampMs / formatClock / formatAge', () => {
  it('timestampMs parses ISO strings and returns 0 for garbage', () => {
    expect(timestampMs('2026-01-01T00:00:00Z')).toBe(Date.UTC(2026, 0, 1))
    expect(timestampMs('not-a-date')).toBe(0)
    expect(timestampMs(null)).toBe(0)
  })

  it('formatClock renders a 24h clock and a placeholder for invalid input', () => {
    expect(formatClock(null)).toBe('--:--:--')
    expect(formatClock('not-a-date')).toBe('--:--:--')
    expect(formatClock('2026-01-01T12:34:56Z')).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })

  it('formatAge formats second/minute/hour scales and rejects negatives', () => {
    expect(formatAge(5)).toBe('5s ago')
    expect(formatAge(120)).toBe('2m ago')
    expect(formatAge(7200)).toBe('2h ago')
    expect(formatAge(-1)).toBe('--')
    expect(formatAge(null)).toBe('--')
  })
})

describe('resolveHealthTone', () => {
  it('maps health vocabulary onto status tones', () => {
    expect(resolveHealthTone('running')).toBe('ok')
    expect(resolveHealthTone('Connected')).toBe('ok')
    expect(resolveHealthTone('failed')).toBe('err')
    expect(resolveHealthTone('offline')).toBe('err')
    expect(resolveHealthTone('stale')).toBe('warn')
    expect(resolveHealthTone('degraded')).toBe('warn')
    expect(resolveHealthTone('something else')).toBe('neutral')
    expect(resolveHealthTone(null)).toBe('neutral')
  })
})

describe('deriveDecisionFeed', () => {
  const log = (overrides: Partial<AgentLog>): AgentLog => ({
    agent_name: 'REASONING_AGENT',
    timestamp: '2026-01-01T10:00:00Z',
    ...overrides,
  })

  it('merges logs, orders, and notifications sorted newest-first', () => {
    const feed = deriveDecisionFeed({
      agentLogs: [log({ action: 'buy', symbol: 'BTC/USD', timestamp: '2026-01-01T10:00:00Z' })],
      orders: [
        {
          order_id: 'o1',
          symbol: 'ETH/USD',
          side: 'long',
          timestamp: '2026-01-01T12:00:00Z',
        } as unknown as Order,
      ],
      notifications: [
        {
          id: 'n1',
          message: 'filled',
          notification_type: 'buy',
          severity: 'info',
          action: 'buy',
          symbol: 'SOL/USD',
          timestamp: '2026-01-01T11:00:00Z',
        } as unknown as Notification,
      ],
    })
    expect(feed.map((i) => i.symbol)).toEqual(['ETH/USD', 'SOL/USD', 'BTC/USD'])
    expect(feed.map((i) => i.source)).toEqual(['order', 'notification', 'decision'])
  })

  it('skips logs that carry no decision signal and caps the feed length', () => {
    const noise = Array.from({ length: SURFACED_DECISION_LIMIT + 10 }, (_, i) =>
      log({ action: 'buy', symbol: 'BTC/USD', id: i, timestamp: `2026-01-01T10:${String(i % 60).padStart(2, '0')}:00Z` }),
    )
    const feed = deriveDecisionFeed({
      agentLogs: [...noise, log({ message: 'heartbeat only', timestamp: '2026-01-01T09:00:00Z' })],
      orders: [],
      notifications: [],
    })
    expect(feed.length).toBe(SURFACED_DECISION_LIMIT)
    expect(feed.every((item) => item.symbol === 'BTC/USD')).toBe(true)
  })
})

describe('deriveAgentActivity', () => {
  it('returns one row per canonical agent, matched by canonical key', () => {
    const rows = deriveAgentActivity({
      agentStatuses: [
        { name: 'signal agent', status: 'active', event_count: 3, last_event: 'tick', last_seen: 0, seconds_ago: 5 } as AgentHeartbeat,
      ],
      agentLogs: [],
    })
    expect(rows.length).toBeGreaterThanOrEqual(ALL_AGENT_NAMES.length)
    const signal = rows.find((r) => r.key === 'SIGNAL_AGENT')
    expect(signal?.status?.event_count).toBe(3)
  })
})
