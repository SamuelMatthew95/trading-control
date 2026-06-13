import { describe, expect, it } from 'vitest'

import {
  actionTone,
  isFallbackDecision,
  signed,
  statusTone,
  summarizeDecisions,
} from '@/lib/cognitive'
import type { DecisionPayload } from '@/types/cognitive'

const mkDecision = (over: Partial<DecisionPayload>): DecisionPayload => ({
  action: 'hold',
  score: 0.3,
  breakdown: {},
  buy_threshold: 0,
  sell_threshold: 0,
  ...over,
})

describe('cognitive helpers', () => {
  it('actionTone distinguishes buy / sell / hold via the Tone tokens', () => {
    expect(actionTone('buy')).toContain('success')
    expect(actionTone('sell')).toContain('danger')
    expect(actionTone('hold')).toContain('muted')
  })

  it('statusTone reflects proposal lifecycle via the Tone tokens', () => {
    expect(statusTone('approved')).toContain('success')
    expect(statusTone('merged')).toContain('success')
    expect(statusTone('rejected')).toContain('danger')
    expect(statusTone('backtesting')).toContain('warning')
    expect(statusTone('generated')).toContain('muted')
  })

  it('signed formats numbers with an explicit sign', () => {
    expect(signed(0.18)).toBe('+0.18')
    expect(signed(-1.2)).toBe('-1.20')
    expect(signed(0.5, 3)).toBe('+0.500')
    expect(signed(null)).toBe('--')
    expect(signed(undefined)).toBe('--')
  })

  it('isFallbackDecision flags rule-based decisions (LLM down)', () => {
    expect(isFallbackDecision(mkDecision({ llm_succeeded: false }))).toBe(true)
    expect(isFallbackDecision(mkDecision({ reasoning_summary: 'fallback: reject_signal' }))).toBe(true)
    expect(isFallbackDecision(mkDecision({ llm_succeeded: true }))).toBe(false)
    expect(isFallbackDecision(mkDecision({}))).toBe(false)
  })

  it('summarizeDecisions aggregates action split, LLM success rate, and confidence', () => {
    const stats = summarizeDecisions([
      mkDecision({ action: 'buy', llm_succeeded: true, confidence: 0.8 }),
      mkDecision({ action: 'sell', llm_succeeded: true, confidence: 0.6 }),
      mkDecision({ action: 'hold', llm_succeeded: false, confidence: 0.2 }),
      mkDecision({ action: 'hold', confidence: 0.4 }),
    ])
    expect(stats.total).toBe(4)
    expect(stats.buys).toBe(1)
    expect(stats.sells).toBe(1)
    expect(stats.holds).toBe(2)
    expect(stats.llmRan).toBe(2)
    expect(stats.fallbacks).toBe(1) // 3 known, 2 ran
    expect(stats.successRate).toBeCloseTo(2 / 3)
    expect(stats.avgConfidence).toBeCloseTo(0.5)
  })

  it('summarizeDecisions reports null success rate when no decision knows its LLM status', () => {
    const stats = summarizeDecisions([mkDecision({ action: 'buy' }), mkDecision({ action: 'hold' })])
    expect(stats.successRate).toBeNull()
    expect(stats.fallbacks).toBe(0)
  })
})
