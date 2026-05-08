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

describe('AgentStatusTable — events column', () => {
  it('shows "no events" when both rt and db counts are zero', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 0, persistedCount: 0 })]}
        showEmpty={false}
      />,
    )
    expect(screen.getByText('no events')).toBeInTheDocument()
    // Old jargon must not return.
    expect(screen.queryByText(/rt:\d/)).not.toBeInTheDocument()
    expect(screen.queryByText(/db:\d/)).not.toBeInTheDocument()
  })

  it('shows "1 event" for a singular count', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 1, persistedCount: 0 })]}
        showEmpty={false}
      />,
    )
    expect(screen.getByText('1 event')).toBeInTheDocument()
  })

  it('uses the LARGER of rt/db (avoids double-counting overlapping streams)', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 24624, persistedCount: 24612 })]}
        showEmpty={false}
      />,
    )
    expect(screen.getByText('24,624 events')).toBeInTheDocument()
    // It must not be the sum.
    expect(screen.queryByText('49,236 events')).not.toBeInTheDocument()
  })

  it('formats large counts with thousand separators', () => {
    render(
      <AgentStatusTable
        agents={[makeAgent({ realtimeCount: 1234, persistedCount: 0 })]}
        showEmpty={false}
      />,
    )
    expect(screen.getByText('1,234 events')).toBeInTheDocument()
  })
})
