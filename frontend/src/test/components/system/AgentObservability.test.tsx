import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { AgentObservability } from '@/components/dashboard/system/AgentObservability'
import type { AgentStatus } from '@/stores/useCodexStore'

const buildAgent = (overrides: Partial<AgentStatus> = {}): AgentStatus => ({
  name: 'SIGNAL_AGENT',
  status: 'ACTIVE',
  event_count: 1234,
  last_event: 'tick BTC/USD',
  last_seen: Date.now() / 1000,
  seconds_ago: 1,
  ...overrides,
})

describe('AgentObservability', () => {
  it('shows empty state when no agents', () => {
    render(<AgentObservability agentStatuses={[]} />)
    expect(screen.getByText(/no agent status yet/i)).toBeInTheDocument()
  })

  it('renders table headers when agents present', () => {
    render(<AgentObservability agentStatuses={[buildAgent()]} />)
    expect(screen.getByText('Agent')).toBeInTheDocument()
    expect(screen.getByText('Status')).toBeInTheDocument()
    expect(screen.getByText('Events')).toBeInTheDocument()
    expect(screen.getByText('Last Action')).toBeInTheDocument()
  })

  it('renders an agent row with name, status, event count and last_event', () => {
    render(<AgentObservability agentStatuses={[buildAgent()]} />)
    expect(screen.getByText('SIGNAL_AGENT')).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('tick BTC/USD')).toBeInTheDocument()
  })

  it('shows dash for empty last_event', () => {
    render(<AgentObservability agentStatuses={[buildAgent({ last_event: '' })]} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('marks ACTIVE status with pulsing emerald dot', () => {
    const { container } = render(<AgentObservability agentStatuses={[buildAgent()]} />)
    expect(container.querySelector('.animate-pulse.bg-emerald-500')).toBeTruthy()
  })

  it('marks inactive status with slate dot', () => {
    const { container } = render(
      <AgentObservability agentStatuses={[buildAgent({ status: 'STALE' })]} />,
    )
    expect(container.querySelector('.bg-slate-400')).toBeTruthy()
  })

  it('renders multiple agents', () => {
    render(
      <AgentObservability
        agentStatuses={[
          buildAgent({ name: 'SIGNAL_AGENT' }),
          buildAgent({ name: 'REASONING_AGENT' }),
          buildAgent({ name: 'EXECUTION_ENGINE' }),
        ]}
      />,
    )
    expect(screen.getByText('SIGNAL_AGENT')).toBeInTheDocument()
    expect(screen.getByText('REASONING_AGENT')).toBeInTheDocument()
    expect(screen.getByText('EXECUTION_ENGINE')).toBeInTheDocument()
  })
})
