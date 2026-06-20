import { describe, it, expect } from 'vitest'

import { coerceProposalContent, proposalStrategyName } from '@/lib/proposal-content'

describe('coerceProposalContent', () => {
  it('passes a plain string through unchanged', () => {
    expect(coerceProposalContent('raise RSI entry to 35')).toBe('raise RSI entry to 35')
  })

  it('extracts reason from a structured challenger-promotion content object', () => {
    const content = {
      strategy: 'mean_reversion',
      shadow_edge: 1.2,
      confidence: 0.62,
      reason: "Shadow challenger 'mean_reversion' beats baseline by +1.20 PnL over 30 shadow trades (win 62%).",
    }
    const text = coerceProposalContent(content)
    expect(text).toContain('beats baseline')
    expect(text).not.toContain('[object Object]')
  })

  it('prefers a design proposal description over dumping its large brief markdown', () => {
    const content = {
      description: 'Govern the underperforming model in the risk-off regime',
      hypothesis_type: 'regime',
      brief: '## Proposal: ...\nlots of markdown\n'.repeat(50),
      evidence: { sample_size: 1 },
    }
    const text = coerceProposalContent(content)
    expect(text).toBe('Govern the underperforming model in the risk-off regime')
    expect(text).not.toContain('## Proposal')
    expect(text).not.toContain('{')
  })

  it('falls back to a strategy summary when the object has no reason', () => {
    expect(coerceProposalContent({ strategy: 'breakout' })).toBe('Challenger: breakout')
  })

  it('JSON-dumps a structured object with neither reason nor strategy (never [object Object])', () => {
    expect(coerceProposalContent({ foo: 'bar' })).toBe('{"foo":"bar"}')
  })

  it('renders an empty object as "" so the UI falls back to strategy_name/proposal_type', () => {
    // Regression: the memory-mode `content: {}` shape must NOT render a bare "{}"
    // as the candidate-change title (the REST/WS/snapshot paths all coerce here).
    expect(coerceProposalContent({})).toBe('')
  })

  it('treats null/undefined as empty string', () => {
    expect(coerceProposalContent(null)).toBe('')
    expect(coerceProposalContent(undefined)).toBe('')
  })
})

describe('proposalStrategyName', () => {
  it('pulls the strategy name out of an object', () => {
    expect(proposalStrategyName({ strategy: 'mean_reversion' })).toBe('mean_reversion')
  })

  it('returns undefined for strings, empty objects, and nullish input', () => {
    expect(proposalStrategyName('text')).toBeUndefined()
    expect(proposalStrategyName({})).toBeUndefined()
    expect(proposalStrategyName(null)).toBeUndefined()
  })
})
