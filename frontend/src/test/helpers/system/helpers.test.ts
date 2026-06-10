import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'

import {
  PIPELINE_HEALTHY_LATENCY_MS,
  computePipeline,
} from '@/components/dashboard/system/helpers'

describe('system/helpers', () => {
  describe('computePipeline', () => {
    const FIXED_NOW = 1_780_000_000_000
    beforeAll(() => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date(FIXED_NOW))
    })
    afterAll(() => {
      vi.useRealTimers()
    })

    it('returns Stalled with empty inputs', () => {
      const result = computePipeline({
        streamStats: {},
        recentEvents: [],
        wsLastMessageTimestamp: null,
        wsMessageRate: 0,
      })
      expect(result.pipelineStatus).toBe('Stalled')
      expect(result.hasMarketData).toBe(false)
      expect(result.effectiveLatencyMs).toBeNull()
      expect(result.signalsCount).toBe(0)
      expect(result.ordersCount).toBe(0)
      expect(result.executionsCount).toBe(0)
      expect(result.pipelineWarning).toBe(false)
    })

    it('uses market_events as fallback when market_ticks is missing', () => {
      const result = computePipeline({
        streamStats: {
          market_events: {
            count: 100,
            lastMessageTimestamp: new Date(FIXED_NOW - 1_000).toISOString(),
          },
        },
        recentEvents: [],
        wsLastMessageTimestamp: null,
        wsMessageRate: 0,
      })
      expect(result.hasMarketData).toBe(true)
      expect(result.marketStageCount).toBe(100)
      expect(result.pipelineStatus).toBe('Healthy')
      expect(result.effectiveLatencyMs).toBeGreaterThanOrEqual(0)
      expect(result.effectiveLatencyMs).toBeLessThan(PIPELINE_HEALTHY_LATENCY_MS)
    })

    it('marks pipelineWarning when signals exist but orders do not', () => {
      const result = computePipeline({
        streamStats: {
          market_ticks: {
            count: 10,
            lastMessageTimestamp: new Date(FIXED_NOW - 100).toISOString(),
          },
          signals: { count: 5, lastMessageTimestamp: null },
          orders: { count: 0, lastMessageTimestamp: null },
        },
        recentEvents: [],
        wsLastMessageTimestamp: null,
        wsMessageRate: 0,
      })
      expect(result.pipelineWarning).toBe(true)
      expect(result.signalsCount).toBe(5)
      expect(result.ordersCount).toBe(0)
    })

    it('returns Degraded when latency exceeds threshold', () => {
      const stale = new Date(FIXED_NOW - PIPELINE_HEALTHY_LATENCY_MS - 1_000).toISOString()
      const result = computePipeline({
        streamStats: {
          market_ticks: { count: 1, lastMessageTimestamp: stale },
        },
        recentEvents: [],
        wsLastMessageTimestamp: null,
        wsMessageRate: 0,
      })
      expect(result.pipelineStatus).toBe('Degraded')
    })

    it('coerces non-finite throughput to 0', () => {
      const result = computePipeline({
        streamStats: {},
        recentEvents: [],
        wsLastMessageTimestamp: null,
        wsMessageRate: Number.NaN,
      })
      expect(result.throughput).toBe(0)
    })

    it('uses recentEvents as last-resort latency source', () => {
      const result = computePipeline({
        streamStats: {},
        recentEvents: [{ stream: 'signals', timestamp: new Date(FIXED_NOW - 500).toISOString() }],
        wsLastMessageTimestamp: null,
        wsMessageRate: 0,
      })
      expect(result.effectiveLatencyMs).toBeGreaterThanOrEqual(0)
      expect(result.effectiveLatencyMs).toBeLessThan(1_000)
    })
  })

  it('exposes the latency threshold constant', () => {
    expect(PIPELINE_HEALTHY_LATENCY_MS).toBe(15_000)
  })
})
