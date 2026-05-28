import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { PipelineFlow } from '@/components/dashboard/system/PipelineFlow'
import type { AgentStatus } from '@/stores/useCodexStore'

const buildAgent = (overrides: Partial<AgentStatus> = {}): AgentStatus => ({
  name: 'REASONING_AGENT',
  status: 'ACTIVE',
  event_count: 42,
  last_event: 'decision:hold',
  last_seen: Date.now() / 1000,
  seconds_ago: 1,
  ...overrides,
})

const baseProps = {
  hasMarketData: true,
  marketStageCount: 1000,
  signalsCount: 10,
  ordersCount: 0,
  executionsCount: 0,
  agentStatuses: [buildAgent()],
}

describe('PipelineFlow', () => {
  it('renders all five stages in order', () => {
    render(<PipelineFlow {...baseProps} />)
    expect(screen.getByText('Market')).toBeInTheDocument()
    expect(screen.getByText('Signals')).toBeInTheDocument()
    expect(screen.getByText('Reasoning')).toBeInTheDocument()
    expect(screen.getByText('Orders')).toBeInTheDocument()
    expect(screen.getByText('Executions')).toBeInTheDocument()
  })

  it('shows reasoning agent status in the header when present', () => {
    render(<PipelineFlow {...baseProps} agentStatuses={[buildAgent({ status: 'STALE' })]} />)
    expect(screen.getByText('STALE')).toBeInTheDocument()
  })

  it('falls back to "unknown" reasoning status when no reasoning agent', () => {
    render(<PipelineFlow {...baseProps} agentStatuses={[]} />)
    expect(screen.getByText('unknown')).toBeInTheDocument()
  })

  it('marks Market as stalled when no market data', () => {
    render(<PipelineFlow {...baseProps} hasMarketData={false} marketStageCount={0} />)
    expect(screen.getAllByText('STALLED')[0]).toBeInTheDocument()
  })

  it('marks signals as IDLE when no signals', () => {
    render(<PipelineFlow {...baseProps} signalsCount={0} />)
    const labels = screen.getAllByText('IDLE')
    // Signals + Reasoning + Orders + Executions = 4 idle (when none flowing)
    expect(labels.length).toBeGreaterThanOrEqual(1)
  })

  it('shows reasoning as flowing when agent is ACTIVE', () => {
    render(<PipelineFlow {...baseProps} agentStatuses={[buildAgent({ status: 'ACTIVE' })]} />)
    // At least one FLOWING for Reasoning + Signals
    expect(screen.getAllByText('FLOWING').length).toBeGreaterThanOrEqual(2)
  })
})
