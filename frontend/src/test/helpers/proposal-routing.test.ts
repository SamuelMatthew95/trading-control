import { describe, it, expect } from 'vitest'

import { proposalRouting } from '@/lib/proposal-routing'

describe('proposalRouting', () => {
  it('routes config-driven parameter changes to an auto-PR', () => {
    const r = proposalRouting('parameter_change')
    expect(r.kind).toBe('config-pr')
    expect(r.label).toBe('Config auto-PR')
  })

  it('routes code/regime changes to a GitHub issue', () => {
    expect(proposalRouting('code_change').kind).toBe('issue')
    expect(proposalRouting('regime_adjustment').kind).toBe('issue')
  })

  it('routes control-plane and tool/prompt types correctly', () => {
    expect(proposalRouting('signal_weight_reduction').kind).toBe('control-plane')
    expect(proposalRouting('agent_suspension').kind).toBe('control-plane')
    expect(proposalRouting('agent_retirement').kind).toBe('control-plane')
    expect(proposalRouting('tool_governance').kind).toBe('tool')
    expect(proposalRouting('prompt_evolution').kind).toBe('prompt')
  })

  it('routes new_agent as mixed (challenger or issue)', () => {
    expect(proposalRouting('new_agent').kind).toBe('mixed')
  })

  it('is case-insensitive and degrades to review for unknown/missing types', () => {
    expect(proposalRouting('PARAMETER_CHANGE').kind).toBe('config-pr')
    expect(proposalRouting('something_else').kind).toBe('unknown')
    expect(proposalRouting(null).kind).toBe('unknown')
    expect(proposalRouting(undefined).label).toBe('Review')
  })
})
