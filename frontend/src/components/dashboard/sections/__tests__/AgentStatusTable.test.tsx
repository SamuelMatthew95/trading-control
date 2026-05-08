import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AgentStatusTable } from '../AgentStatusTable'
import type { AgentSummary } from '@/lib/types'

function makeAgent(overrides: Partial<AgentSummary>): AgentSummary {
  return {
    name: 'signal_agent',
    realtimeCount: 0,
    persistedCount: 0,
    lastSeen: null,
    status: 'Idle',
    tier: 'inactive',
    source: 'realtime',
    ...overrides,
  }
}

describe('AgentStatusTable', () => {
  it('shows em-dash when both rt and db counts are zero', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 0, persistedCount: 0 })]}
        showEmpty={false}
      />,
    )
    // Both the events column and the last-seen column collapse to "—"
    // when there's no signal at all; assert at least one is present and
    // the noisy `rt:0 · db:0` form is gone.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByText('rt:0 · db:0')).not.toBeInTheDocument()
  })

  it('shows the rt:X · db:Y format when at least one count is non-zero', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 5, persistedCount: 3 })]}
        showEmpty={false}
      />,
    )
    expect(screen.getByText('rt:5 · db:3')).toBeInTheDocument()
  })

  it('shows the rt:X · db:0 format when only realtime is non-zero', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 5, persistedCount: 0 })]}
        showEmpty={false}
      />,
    )
    expect(screen.getByText('rt:5 · db:0')).toBeInTheDocument()
  })
})
