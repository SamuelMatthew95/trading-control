import { describe, expect, it } from 'vitest'
import { buildDashboardSummary, buildFallbackPerformanceSummary } from '@/lib/dashboard/selectors'

const isClosedTrade = (order: Record<string, unknown>) => order.status === 'filled'

describe('dashboard selectors', () => {
  it('builds dashboard summary', () => {
    const summary = buildDashboardSummary({
      orders: [{ pnl: 10, status: 'filled' }, { pnl: -5, status: 'filled' }],
      positions: [{ side: 'long' }, { side: 'flat' }],
      dailyChangeFromMetric: null,
      dailyChangeFromDashboard: null,
      baseEquity: 100,
      isClosedTrade,
    })

    expect(summary.dailyPnlNumeric).toBe(5)
    expect(summary.winRate).toBe(50)
    expect(summary.activePositions).toBe(1)
    expect(summary.dailyChange).toBe(5)
  })

  it('builds fallback performance summary', () => {
    const fallback = buildFallbackPerformanceSummary([
      { pnl: 10, status: 'filled' },
      { pnl: -3, status: 'filled' },
      { pnl: 2, status: 'open' },
    ], isClosedTrade)

    expect(fallback).not.toBeNull()
    expect(fallback?.total_pnl).toBe(7)
    expect(fallback?.best_trade).toBe(10)
    expect(fallback?.worst_trade).toBe(-3)
  })
})
