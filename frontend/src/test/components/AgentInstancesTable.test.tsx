import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { AgentInstancesTable } from '@/components/dashboard/agents/AgentInstancesTable'
import type { AgentInstance, AgentStatus } from '@/stores/useCodexStore'

const instances: AgentInstance[] = [
  {
    id: 'i1',
    instance_key: 'signal-1',
    pool_name: 'signal',
    status: 'active',
    started_at: '2026-05-30T00:00:00Z',
    retired_at: null,
    event_count: 42,
    uptime_seconds: 3661,
  },
]

function activeStatus(): AgentStatus[] {
  return [
    {
      name: 'SIGNAL_AGENT',
      status: 'ACTIVE',
      event_count: 1,
      last_event: 'tick',
      last_seen: 0,
      seconds_ago: 1,
    },
  ]
}

describe('AgentInstancesTable', () => {
  it('renders a row per instance with key, status, and uptime', () => {
    const { container } = render(
      <AgentInstancesTable agentInstances={instances} agentStatuses={[]} />,
    )
    expect(screen.getByText('signal-1')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(container.textContent).toContain('1h 1m') // 3661s uptime
  })

  it('warns when agents report ACTIVE heartbeats but no instances exist', () => {
    render(<AgentInstancesTable agentInstances={[]} agentStatuses={activeStatus()} />)
    expect(screen.getByText('No instances registered yet')).toBeInTheDocument()
    expect(screen.getByText(/no lifecycle records were returned/)).toBeInTheDocument()
  })

  it('shows a plain empty state when nothing is active', () => {
    render(<AgentInstancesTable agentInstances={[]} agentStatuses={[]} />)
    expect(screen.getByText('No instances registered yet')).toBeInTheDocument()
    expect(screen.queryByText(/no lifecycle records were returned/)).toBeNull()
  })
})
