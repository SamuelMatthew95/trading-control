import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SystemDashboard } from '@/components/dashboard/system'
import type { SystemDashboardProps } from '@/components/dashboard/system'

const baseProps: SystemDashboardProps = {
  wsConnected: false,
  wsMessageCount: 0,
  wsLastMessageTimestamp: null,
  wsDiagnostics: { reconnectAttempts: 0, messageRate: 0, lastError: null },
  streamStats: {},
  recentEvents: [],
  agentStatuses: [],
  prices: {},
  positions: [],
  tradeFeed: [],
  pricesFetched: false,
  isInMemoryMode: false,
  resolvedPerformanceSummary: null,
  apiHealth: {
    dashboardState: 'pending',
    agentInstances: 'pending',
    eventHistory: 'pending',
  },
  systemFeedError: null,
  llmAvailable: null,
  llmProvider: '',
  persistedCounts: [],
  persistedEvents: [],
  persistedLogs: [],
  setActiveTraceId: vi.fn(),
}

describe('SystemDashboard integration', () => {
  it('renders without crashing on empty state', () => {
    expect(() => render(<SystemDashboard {...baseProps} />)).not.toThrow()
  })

  it('shows all top-level section titles', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getByText('Pipeline Flow')).toBeInTheDocument()
    expect(screen.getByText('Connection Diagnostics')).toBeInTheDocument()
    expect(screen.getByText('Stream Activity')).toBeInTheDocument()
    expect(screen.getByText('P&L Clarity')).toBeInTheDocument()
    expect(screen.getByText('Agent Observability')).toBeInTheDocument()
    expect(screen.getByText('Recent Events')).toBeInTheDocument()
    expect(screen.getByText('Persisted Event History')).toBeInTheDocument()
  })

  it('renders all six hero metrics', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getByRole('group', { name: /pipeline/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /data latency/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /throughput/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /websocket/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /database/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /llm/i })).toBeInTheDocument()
  })

  it('shows Stalled pipeline status on cold start', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getAllByText('Stalled').length).toBeGreaterThan(0)
  })

  it('surfaces the no-market-data alert when nothing has streamed', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getByText(/no market data received/i)).toBeInTheDocument()
  })

  it('surfaces rule-based alert when llmAvailable=false', () => {
    render(<SystemDashboard {...baseProps} llmAvailable={false} llmProvider="anthropic" />)
    expect(screen.getByText(/rule-based reasoning mode/i)).toBeInTheDocument()
  })

  it('reflects WS connected state and message count', () => {
    render(
      <SystemDashboard
        {...baseProps}
        wsConnected={true}
        wsMessageCount={42}
        wsDiagnostics={{ reconnectAttempts: 1, messageRate: 1.25, lastError: null }}
      />,
    )
    // There are multiple "Connected" elements (hero + diagnostics) — at least one must exist
    expect(screen.getAllByText(/Connected/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/42 total msgs/)).toBeInTheDocument()
  })

  it('hides alerts when system is fully healthy', () => {
    render(
      <SystemDashboard
        {...baseProps}
        wsConnected={true}
        streamStats={{
          market_ticks: {
            count: 100,
            lastMessageTimestamp: new Date().toISOString(),
          },
        }}
        apiHealth={{
          dashboardState: 'ok',
          agentInstances: 'ok',
          eventHistory: 'ok',
        }}
        llmAvailable={true}
        llmProvider="openai"
      />,
    )
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows the persistence-disabled alert when no persistence signals are present', () => {
    render(
      <SystemDashboard
        {...baseProps}
        wsConnected={true}
        llmAvailable={true}
        llmProvider="openai"
        streamStats={{
          market_ticks: {
            count: 100,
            lastMessageTimestamp: new Date().toISOString(),
          },
        }}
        apiHealth={{
          dashboardState: 'ok',
          agentInstances: 'ok',
          eventHistory: 'error',
        }}
      />,
    )
    expect(screen.getByText(/persistence disabled/i)).toBeInTheDocument()
  })

  it('treats in-memory mode as persistence enabled', () => {
    render(
      <SystemDashboard
        {...baseProps}
        isInMemoryMode
        wsConnected={true}
        llmAvailable={true}
        llmProvider="openai"
        streamStats={{
          market_ticks: {
            count: 100,
            lastMessageTimestamp: new Date().toISOString(),
          },
        }}
        apiHealth={{
          dashboardState: 'ok',
          agentInstances: 'ok',
          eventHistory: 'error',
        }}
      />,
    )
    expect(screen.queryByText(/persistence disabled/i)).toBeNull()
  })
})
