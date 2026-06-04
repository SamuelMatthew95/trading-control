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
  orders: [],
  agentLogs: [],
  notifications: [],
  proposals: [],
  riskAlerts: [],
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
  regime: 'Neutral',
  killSwitchActive: false,
  setActiveTraceId: vi.fn(),
}

describe('SystemDashboard integration', () => {
  it('renders without crashing on empty state', () => {
    expect(() => render(<SystemDashboard {...baseProps} />)).not.toThrow()
  })

  it('shows all command center section titles', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getByText('Command Center')).toBeInTheDocument()
    expect(screen.getByText('Live Decision Feed')).toBeInTheDocument()
    expect(screen.getByText('Trace Explorer')).toBeInTheDocument()
    expect(screen.getByText('Cognitive Evolution')).toBeInTheDocument()
    expect(screen.getByText('Agent Activity')).toBeInTheDocument()
    expect(screen.getByText('System Health')).toBeInTheDocument()
    expect(screen.getByText('Proposal Center')).toBeInTheDocument()
  })

  it('renders the six operator headline metrics', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getByText('Net PnL')).toBeInTheDocument()
    expect(screen.getByText('Daily PnL')).toBeInTheDocument()
    expect(screen.getByText('Open Exposure')).toBeInTheDocument()
    expect(screen.getByText('Active Positions')).toBeInTheDocument()
    expect(screen.getByText('Current Regime')).toBeInTheDocument()
    expect(screen.getByText('Risk State')).toBeInTheDocument()
  })

  it('sizes the Command Center card to its metrics instead of stretching it', () => {
    // Regression: the card sat in a 2-col grid next to the taller Operator
    // controls panel and stretched to match it, leaving a large empty band
    // below the single KPI row. self-start keeps it sized to its content.
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getByText('Command Center').closest('.self-start')).not.toBeNull()
  })

  it('shows stalled data health on cold start', () => {
    render(<SystemDashboard {...baseProps} />)
    expect(screen.getAllByText('Stalled').length).toBeGreaterThan(0)
    expect(screen.getByText('No ticks')).toBeInTheDocument()
  })

  it('surfaces rule-based LLM fallback when llmAvailable=false', () => {
    render(<SystemDashboard {...baseProps} llmAvailable={false} llmProvider="anthropic" />)
    expect(screen.getAllByText('Fallback').length).toBeGreaterThan(0)
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
    expect(screen.getByText('42 msgs')).toBeInTheDocument()
  })

  it('shows healthy compact indicators when system is fully healthy', () => {
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
    expect(screen.getAllByText('Healthy').length).toBeGreaterThan(0)
  })

  it('shows database memory mode as a compact warning indicator', () => {
    render(
      <SystemDashboard
        {...baseProps}
        isInMemoryMode
        wsConnected={true}
        llmAvailable={true}
        llmProvider="openai"
      />,
    )
    expect(screen.getByText('Memory')).toBeInTheDocument()
  })

  it('renders decision feed entries from agent logs', () => {
    render(
      <SystemDashboard
        {...baseProps}
        agentLogs={[
          {
            agent_name: 'REASONING_AGENT',
            event_type: 'decision',
            action: 'buy',
            symbol: 'NVDA',
            confidence: 0.78,
            primary_edge: 'Momentum positive; Risk acceptable',
            trace_id: 'trace-1',
            timestamp: '2026-06-01T09:42:15Z',
          },
        ]}
      />,
    )

    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.getByText('NVDA')).toBeInTheDocument()
    expect(screen.getByText('Confidence: 78.0%')).toBeInTheDocument()
  })
})
