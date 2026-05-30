import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SystemDiagnostics } from '@/components/dashboard/agents/SystemDiagnostics'
import type { AgentLog, AgentStatus } from '@/stores/useCodexStore'
import type { ApiHealth } from '@/hooks/useRestPoll'

const wiring = { heartbeatAgeMs: 5000, instanceAgeMs: null, logAgeMs: 1000 }
const apiHealth: ApiHealth = {
  dashboardState: 'ok',
  agentInstances: 'ok',
  eventHistory: 'error',
}

function statuses(n: number): AgentStatus[] {
  return Array.from({ length: n }, (_, i) => ({
    name: `A${i}`,
    status: 'ACTIVE',
    event_count: 0,
    last_event: '',
    last_seen: 0,
    seconds_ago: 0,
  }))
}

function logs(n: number): AgentLog[] {
  return Array.from({ length: n }, () => ({ agent_name: 'A', timestamp: '' }))
}

describe('SystemDiagnostics', () => {
  it('shows DB-connected mode, source counts, and API health badges', () => {
    const { container } = render(
      <SystemDiagnostics
        isInMemoryMode={false}
        agentStatuses={statuses(2)}
        agentInstances={[]}
        agentLogs={logs(3)}
        wiringFreshness={wiring}
        apiHealth={apiHealth}
      />,
    )
    expect(screen.getByText('DB: Connected')).toBeInTheDocument()
    expect(container.textContent).toContain('dashboard/state: ok')
    expect(container.textContent).toContain('history/events: error')
  })

  it('flags in-memory fallback mode', () => {
    render(
      <SystemDiagnostics
        isInMemoryMode={true}
        agentStatuses={[]}
        agentInstances={[]}
        agentLogs={[]}
        wiringFreshness={wiring}
        apiHealth={apiHealth}
      />,
    )
    expect(screen.getByText('DB: In-Memory Fallback')).toBeInTheDocument()
  })
})
