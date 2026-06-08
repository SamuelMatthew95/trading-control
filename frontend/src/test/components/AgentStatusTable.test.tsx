import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { AgentStatusTable } from '@/components/dashboard/agents/AgentStatusTable'
import type { AgentSummary } from '@/lib/agent-pipeline'
import type { AgentInstance } from '@/stores/useCodexStore'

const agents: AgentSummary[] = [
  {
    name: 'SIGNAL_AGENT',
    status: 'Live',
    eventCount: 1234,
    lastSeen: new Date('2026-05-30T00:00:00Z'),
    tier: 'active',
    source: 'realtime',
  },
]

const instances: AgentInstance[] = [
  {
    id: 'i1',
    instance_key: 'signal-1',
    pool_name: 'SIGNAL_AGENT',
    status: 'active',
    started_at: '2026-05-30T00:00:00Z',
    retired_at: null,
    event_count: 42,
    uptime_seconds: 3661,
  },
]

describe('AgentStatusTable', () => {
  it('renders a row per agent with status, source label, and event count', () => {
    const { container } = render(
      <AgentStatusTable realAgents={agents} agentInstances={[]} showNoAgentDataMessage={false} />,
    )
    expect(screen.getByText('Agent Status')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(screen.getByText('Realtime')).toBeInTheDocument()
    expect(container.textContent).toContain('1,234 events')
  })

  it('folds instance uptime into the per-agent row (merged source of truth)', () => {
    const { container } = render(
      <AgentStatusTable realAgents={agents} agentInstances={instances} showNoAgentDataMessage={false} />,
    )
    expect(screen.getByText('Uptime')).toBeInTheDocument()
    expect(container.textContent).toContain('1h 1m') // 3661s uptime, from the matching instance
  })

  it('shows the empty state when the grace period elapses with no agent data', () => {
    render(<AgentStatusTable realAgents={[]} agentInstances={[]} showNoAgentDataMessage={true} />)
    expect(screen.getByText('No active agents')).toBeInTheDocument()
  })

  it('drills into an agent on row click and keyboard when onSelect is wired', () => {
    const onSelect = vi.fn()
    render(
      <AgentStatusTable
        realAgents={agents}
        agentInstances={[]}
        showNoAgentDataMessage={false}
        onSelect={onSelect}
      />,
    )
    const row = screen.getByRole('button', { name: /view .* details/i })
    fireEvent.click(row)
    expect(onSelect).toHaveBeenCalledWith('SIGNAL_AGENT')

    fireEvent.keyDown(row, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledTimes(2)
  })

  it('rows are non-interactive (no button role) when onSelect is absent', () => {
    render(
      <AgentStatusTable realAgents={agents} agentInstances={[]} showNoAgentDataMessage={false} />,
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
