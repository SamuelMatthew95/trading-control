import { describe, it, expect } from 'vitest'

import { extractToolInvocations, summarizeToolOutputs } from '@/lib/decision-tools'

describe('extractToolInvocations', () => {
  it('returns an empty array when tools_used is missing or not an array', () => {
    expect(extractToolInvocations({})).toEqual([])
    expect(extractToolInvocations({ tools_used: 'nope' })).toEqual([])
    expect(extractToolInvocations({ tools_used: null })).toEqual([])
  })

  it('normalizes a real tool ledger and skips malformed entries', () => {
    const tools = extractToolInvocations({
      tools_used: [
        { name: 'get_ic_weights', latency_ms: 12, success: true, outputs: { ic_weights: { momentum: 0.4 } } },
        { name: 'query_similar_trades', latency_ms: 32, success: false, outputs: { count: 7 } },
        null,
        'garbage',
        42,
      ],
    })
    expect(tools).toHaveLength(2)
    expect(tools[0]).toMatchObject({ name: 'get_ic_weights', latency_ms: 12, success: true })
    expect(tools[1]).toMatchObject({ name: 'query_similar_trades', success: false })
    expect(tools[1].outputs).toEqual({ count: 7 })
  })
})

describe('summarizeToolOutputs', () => {
  it('summarizes similar-trade counts with correct pluralization', () => {
    expect(summarizeToolOutputs({ count: 7 })).toBe('7 examples')
    expect(summarizeToolOutputs({ count: 1 })).toBe('1 example')
    expect(summarizeToolOutputs({ count: 0 })).toBe('0 examples')
  })

  it('summarizes IC weights as factor:value pairs (capped at three)', () => {
    const summary = summarizeToolOutputs({
      ic_weights: { momentum: 0.42, mean_reversion: 0.18, volume: 0.23, extra: 0.05 },
    })
    expect(summary).toContain('momentum 0.42')
    expect(summary).toContain('mean_reversion 0.18')
    // Capped at three factors.
    expect(summary?.split(' · ')).toHaveLength(3)
  })

  it('summarizes cross-stream confluence (composite score + signal type)', () => {
    expect(summarizeToolOutputs({ composite_score: 0.75, signal_type: 'momentum_buy' })).toBe(
      'confluence 0.75 · momentum_buy',
    )
    // Score alone (signal type absent or empty) still renders.
    expect(summarizeToolOutputs({ composite_score: 0.5, signal_type: '' })).toBe('confluence 0.50')
  })

  it('returns null when there is nothing decision-relevant to show', () => {
    expect(summarizeToolOutputs(undefined)).toBeNull()
    expect(summarizeToolOutputs({})).toBeNull()
    expect(summarizeToolOutputs({ unrelated: 'x' })).toBeNull()
  })
})
