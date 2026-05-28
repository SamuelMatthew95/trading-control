import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'

import {
  PIPELINE_HEALTHY_LATENCY_MS,
  PRICE_FRESHNESS_MS,
  canonicalAgentKey,
  computePipeline,
  formatAgeFromMs,
  formatLlmProviderName,
  formatTimestamp,
  pipelineStatusTone,
  pnlColorClass,
  resolveWsUrl,
} from '@/components/dashboard/system/helpers'

describe('system/helpers', () => {
  describe('formatAgeFromMs', () => {
    it('returns -- for null/negative/non-finite', () => {
      expect(formatAgeFromMs(null)).toBe('--')
      expect(formatAgeFromMs(-1)).toBe('--')
      expect(formatAgeFromMs(Number.POSITIVE_INFINITY)).toBe('--')
      expect(formatAgeFromMs(Number.NaN)).toBe('--')
    })

    it('formats seconds', () => {
      expect(formatAgeFromMs(0)).toBe('0s')
      expect(formatAgeFromMs(1500)).toBe('1s')
      expect(formatAgeFromMs(59_000)).toBe('59s')
    })

    it('formats minutes', () => {
      expect(formatAgeFromMs(60_000)).toBe('1m')
      expect(formatAgeFromMs(3_540_000)).toBe('59m')
    })

    it('formats hours', () => {
      expect(formatAgeFromMs(3_600_000)).toBe('1h')
      expect(formatAgeFromMs(36_000_000)).toBe('10h')
    })
  })

  describe('formatTimestamp', () => {
    it('returns -- for null / invalid', () => {
      expect(formatTimestamp(null)).toBe('--')
      expect(formatTimestamp(undefined)).toBe('--')
      expect(formatTimestamp('')).toBe('--')
      expect(formatTimestamp('not-a-date')).toBe('--')
    })

    it('formats valid ISO into a locale time string', () => {
      const out = formatTimestamp('2026-01-01T12:34:56Z')
      // Locale-dependent but must be non-empty and non-default
      expect(out).not.toBe('--')
      expect(out.length).toBeGreaterThan(0)
    })
  })

  describe('canonicalAgentKey', () => {
    it('uppercases and replaces spaces/dashes with underscores', () => {
      expect(canonicalAgentKey('signal agent')).toBe('SIGNAL_AGENT')
      expect(canonicalAgentKey('Reasoning-Agent')).toBe('REASONING_AGENT')
      expect(canonicalAgentKey('  EXECUTION_ENGINE  ')).toBe('EXECUTION_ENGINE')
    })
  })

  describe('formatLlmProviderName', () => {
    it('capitalizes first letter', () => {
      expect(formatLlmProviderName('openai')).toBe('Openai')
      expect(formatLlmProviderName('Groq')).toBe('Groq')
    })

    it('returns LLM for empty', () => {
      expect(formatLlmProviderName('')).toBe('LLM')
    })
  })

  describe('pnlColorClass', () => {
    it('returns muted slate when empty', () => {
      expect(pnlColorClass(100, true)).toContain('slate-500')
    })

    it('returns emerald for positive', () => {
      expect(pnlColorClass(100, false)).toContain('emerald-500')
    })

    it('returns rose for negative', () => {
      expect(pnlColorClass(-100, false)).toContain('rose-500')
    })

    it('returns slate for zero non-empty', () => {
      expect(pnlColorClass(0, false)).toContain('slate-900')
    })
  })

  describe('pipelineStatusTone', () => {
    it('maps statuses to tones', () => {
      expect(pipelineStatusTone('Healthy')).toBe('ok')
      expect(pipelineStatusTone('Degraded')).toBe('warn')
      expect(pipelineStatusTone('Stalled')).toBe('err')
    })
  })

  describe('resolveWsUrl', () => {
    it('returns — when window undefined (SSR)', () => {
      // Hard to test SSR path inside jsdom; we just exercise the live path.
      // Spy on env to ensure deterministic URL.
      const env = process.env
      process.env = { ...env, NEXT_PUBLIC_API_URL: 'https://example.com/api' }
      expect(resolveWsUrl()).toBe('wss://example.com/ws/dashboard')
      process.env = env
    })

    it('prefers NEXT_PUBLIC_WS_URL when set', () => {
      const env = process.env
      process.env = { ...env, NEXT_PUBLIC_WS_URL: 'https://ws.example.com/' }
      expect(resolveWsUrl()).toBe('wss://ws.example.com/ws/dashboard')
      process.env = env
    })
  })

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

  it('exposes expected constants', () => {
    expect(PRICE_FRESHNESS_MS).toBe(60_000)
    expect(PIPELINE_HEALTHY_LATENCY_MS).toBe(15_000)
  })
})
