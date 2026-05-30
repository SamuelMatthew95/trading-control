import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { AgentStatusTable } from '@/components/dashboard/agents/AgentStatusTable'
import type { AgentSummary } from '@/lib/agent-pipeline'

const agents: AgentSummary[] = [
  {
    name: 'SIGNAL_AGENT',
    status: 'Live',
    realtimeCount: 1000,
    persistedCount: 234,
    lastSeen: new Date('2026-05-30T00:00:00Z'),
    tier: 'active',
    source: 'realtime',
  },
]

describe('AgentStatusTable', () => {
  it('renders a row per agent with status, source label, and event count', () => {
    const { container } = render(
      <AgentStatusTable realAgents={agents} showNoAgentDataMessage={false} />,
    )
    expect(screen.getByText('Agent Status')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(screen.getByText('Realtime')).toBeInTheDocument()
    expect(container.textContent).toContain('1,234 events')
  })

  it('shows the empty state when the grace period elapses with no agent data', () => {
    render(<AgentStatusTable realAgents={[]} showNoAgentDataMessage={true} />)
    expect(screen.getByText('No active agents')).toBeInTheDocument()
  })
})
