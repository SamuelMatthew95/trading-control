import { describe, it, expect } from 'vitest'
import {
  buildAgentSummaries,
  buildDashboardSummary,
  buildFallbackPerformanceSummary,
  buildTradeFeedAggregates,
  buildWiringFreshness,
  getMetric,
  parseHeartbeatTimestamp,
} from '../selectors'

import type {
  AgentInstance,
  AgentLog,
  AgentStatus,
  Order,
  Position,
  SystemMetric,
  TradeFeedItem,
} from '@/stores/useCodexStore'

const FIXED_NOW = new Date('2026-05-08T12:00:00Z').getTime()

function isoMinusSeconds(seconds: number): string {
  return new Date(FIXED_NOW - seconds * 1000).toISOString()
}

describe('parseHeartbeatTimestamp', () => {
  it('reads last_seen_at when present', () => {
    const status = {
      name: 'X',
      status: 'ok',
      event_count: 0,
      last_event: '',
      last_seen: 0,
      last_seen_at: '2026-05-08T12:00:00Z',
      seconds_ago: 0,
    } as AgentStatus
    const result = parseHeartbeatTimestamp(status)
    expect(result?.toISOString()).toBe('2026-05-08T12:00:00.000Z')
  })

  it('falls back to last_seen epoch', () => {
    const status = {
      name: 'X',
      status: 'ok',
      event_count: 0,
      last_event: '',
      last_seen: 1700000000,
      seconds_ago: 0,
    } as AgentStatus
    expect(parseHeartbeatTimestamp(status)).toBeInstanceOf(Date)
  })

  it('returns null when nothing parseable', () => {
    const status = {
      name: 'X',
      status: 'ok',
      event_count: 0,
      last_event: '',
      last_seen: 0,
      seconds_ago: 0,
    } as AgentStatus
    expect(parseHeartbeatTimestamp(status)).toBeNull()
  })
})

describe('getMetric', () => {
  const metrics: SystemMetric[] = [
    { metric_name: 'portfolio_value', value: 100_000 },
    { metric_name: 'daily_change_pct', value: 1.25 },
    { metric_name: 'broken', value: NaN },
  ]
  it('returns numeric value when found', () => {
    expect(getMetric(metrics, 'portfolio_value')).toBe(100_000)
  })
  it('returns null when not found', () => {
    expect(getMetric(metrics, 'missing')).toBeNull()
  })
  it('returns null on NaN', () => {
    expect(getMetric(metrics, 'broken')).toBeNull()
  })
})

describe('buildDashboardSummary', () => {
  it('zero orders, zero positions → all zero/null', () => {
    const result = buildDashboardSummary([], [], [], null)
    expect(result.dailyPnlNumeric).toBe(0)
    expect(result.winRate).toBeNull()
    expect(result.activePositions).toBe(0)
    expect(result.hasOrders).toBe(false)
    expect(result.hasClosedTrades).toBe(false)
  })

  it('counts active long/short positions', () => {
    const positions = [
      { side: 'long', quantity: 1 },
      { side: 'short', quantity: 1 },
      { side: undefined, quantity: 1 },
    ] as unknown as Position[]
    const result = buildDashboardSummary([], positions, [], null)
    expect(result.activePositions).toBe(2)
  })

  it('aggregates daily P&L across orders', () => {
    const orders = [
      { pnl: 50 } as unknown as Order,
      { pnl: -20 } as unknown as Order,
      { pnl: 'garbage' } as unknown as Order,
    ]
    const result = buildDashboardSummary(orders, [], [], null)
    expect(result.dailyPnlNumeric).toBe(30)
    expect(result.hasOrders).toBe(true)
  })

  it('computes win rate over closed trades only', () => {
    const orders = [
      { pnl: 10, status: 'filled' },
      { pnl: -5, status: 'filled' },
      { pnl: 5, status: 'filled' },
      { pnl: 20, status: 'pending' },
    ] as unknown as Order[]
    const result = buildDashboardSummary(orders, [], [], null)
    expect(result.hasClosedTrades).toBe(true)
    expect(result.winRate).toBeCloseTo((2 / 3) * 100)
  })

  it('uses metric daily_change_pct when present', () => {
    const result = buildDashboardSummary([], [], [{ metric_name: 'daily_change_pct', value: 1.5 }], null)
    expect(result.dailyChange).toBe(1.5)
  })

  it('falls back to dashboardData.daily_change_pct', () => {
    const result = buildDashboardSummary([], [], [], { daily_change_pct: -0.5 })
    expect(result.dailyChange).toBe(-0.5)
  })

  it('computes daily change from base equity when no metric exists', () => {
    const orders = [{ pnl: 100, status: 'filled' }] as unknown as Order[]
    const result = buildDashboardSummary(
      orders,
      [],
      [{ metric_name: 'portfolio_value', value: 100_000 }],
      null,
    )
    expect(result.dailyChange).toBeCloseTo(0.1)
  })
})

describe('buildFallbackPerformanceSummary', () => {
  it('returns null when no closed orders', () => {
    expect(buildFallbackPerformanceSummary([])).toBeNull()
  })

  it('aggregates closed pnls', () => {
    const orders = [
      { pnl: 100, status: 'filled' },
      { pnl: -50, status: 'filled' },
      { pnl: 25, status: 'closed' },
    ] as unknown as Order[]
    const result = buildFallbackPerformanceSummary(orders)
    expect(result?.total_pnl).toBe(75)
    expect(result?.best_trade).toBe(100)
    expect(result?.worst_trade).toBe(-50)
    expect(result?.win_rate).toBeCloseTo(2 / 3)
  })
})

describe('buildAgentSummaries', () => {
  it('empty inputs → empty array', () => {
    expect(buildAgentSummaries([], [], [], FIXED_NOW)).toEqual([])
  })

  it('groups logs by canonical key and marks Live within window', () => {
    const logs = [
      { agent_name: 'signal_agent', timestamp: isoMinusSeconds(2) },
      { agent_name: 'signal_agent', timestamp: isoMinusSeconds(1) },
    ] as unknown as AgentLog[]
    const result = buildAgentSummaries(logs, [], [], FIXED_NOW)
    expect(result).toHaveLength(1)
    expect(result[0].realtimeCount).toBe(2)
    expect(result[0].status).toBe('Live')
    expect(result[0].source).toBe('realtime')
  })

  it('marks Stale when older than live window but within stale window', () => {
    const logs = [
      { agent_name: 'signal_agent', timestamp: isoMinusSeconds(60) },
    ] as unknown as AgentLog[]
    const result = buildAgentSummaries(logs, [], [], FIXED_NOW)
    expect(result[0].status).toBe('Stale')
  })

  it('marks Idle when older than stale threshold', () => {
    const logs = [
      { agent_name: 'signal_agent', timestamp: isoMinusSeconds(600) },
    ] as unknown as AgentLog[]
    const result = buildAgentSummaries(logs, [], [], FIXED_NOW)
    expect(result[0].status).toBe('Idle')
  })

  it('merges agentStatuses heartbeat into existing log entry as hybrid', () => {
    // Both must canonicalize to the same key (no camelCase split — only
    // spaces/hyphens become underscores).
    const logs = [
      { agent_name: 'signal_agent', timestamp: isoMinusSeconds(2) },
    ] as unknown as AgentLog[]
    const statuses = [
      {
        name: 'signal_agent',
        status: 'ok',
        event_count: 5,
        last_event: '',
        last_seen: 0,
        last_seen_at: isoMinusSeconds(1),
        seconds_ago: 1,
      },
    ] as unknown as AgentStatus[]
    const result = buildAgentSummaries(logs, statuses, [], FIXED_NOW)
    expect(result[0].source).toBe('hybrid')
    expect(result[0].realtimeCount).toBeGreaterThanOrEqual(5)
  })

  it('sorts Live before Stale before Idle', () => {
    const logs = [
      { agent_name: 'idle_agent', timestamp: isoMinusSeconds(600) },
      { agent_name: 'live_agent', timestamp: isoMinusSeconds(2) },
      { agent_name: 'stale_agent', timestamp: isoMinusSeconds(60) },
    ] as unknown as AgentLog[]
    const result = buildAgentSummaries(logs, [], [], FIXED_NOW)
    expect(result.map((a) => a.status)).toEqual(['Live', 'Stale', 'Idle'])
  })

  it('absorbs agentInstances entries as persisted source', () => {
    const instances = [
      {
        id: 'i1',
        instance_key: 'k',
        pool_name: 'NewAgent',
        status: 'active',
        started_at: isoMinusSeconds(2),
        retired_at: null,
        event_count: 7,
        uptime_seconds: 5,
      },
    ] as AgentInstance[]
    const result = buildAgentSummaries([], [], instances, FIXED_NOW)
    expect(result).toHaveLength(1)
    expect(result[0].source).toBe('persisted')
    expect(result[0].persistedCount).toBe(7)
  })
})

describe('buildTradeFeedAggregates', () => {
  it('empty trade feed → all zeros', () => {
    const result = buildTradeFeedAggregates([])
    expect(result).toEqual({ realizedPnl: 0, totalTrades: 0, wins: 0, pnlWinRate: 0 })
  })

  it('aggregates pnl + counts wins + ignores null pnl', () => {
    const trades = [
      { pnl: 100 },
      { pnl: -25 },
      { pnl: 50 },
      { pnl: null },
    ] as unknown as TradeFeedItem[]
    const result = buildTradeFeedAggregates(trades)
    expect(result.realizedPnl).toBe(125)
    expect(result.totalTrades).toBe(3)
    expect(result.wins).toBe(2)
    expect(result.pnlWinRate).toBeCloseTo((2 / 3) * 100)
  })
})

describe('buildWiringFreshness', () => {
  it('returns nulls for empty inputs', () => {
    const result = buildWiringFreshness([], [], [], FIXED_NOW)
    expect(result.heartbeatAgeMs).toBeNull()
    expect(result.instanceAgeMs).toBeNull()
    expect(result.logAgeMs).toBeNull()
  })

  it('returns ages in ms relative to now', () => {
    const status = {
      name: 'X',
      status: 'ok',
      event_count: 0,
      last_event: '',
      last_seen: 0,
      last_seen_at: isoMinusSeconds(5),
      seconds_ago: 5,
    } as AgentStatus
    const instance = {
      id: 'i',
      instance_key: 'k',
      pool_name: 'p',
      status: 'active',
      started_at: isoMinusSeconds(10),
      retired_at: null,
      event_count: 0,
      uptime_seconds: 0,
    } as AgentInstance
    const log = { agent_name: 'A', timestamp: isoMinusSeconds(15) } as unknown as AgentLog
    const result = buildWiringFreshness([status], [instance], [log], FIXED_NOW)
    expect(result.heartbeatAgeMs).toBeCloseTo(5_000, -2)
    expect(result.instanceAgeMs).toBeCloseTo(10_000, -2)
    expect(result.logAgeMs).toBeCloseTo(15_000, -2)
  })
})
