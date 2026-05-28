import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ConnectionDiagnostics } from '@/components/dashboard/system/ConnectionDiagnostics'
import type { ApiHealth, WsDiagnosticsLike } from '@/components/dashboard/system/types'

const wsDiagnostics: WsDiagnosticsLike = {
  reconnectAttempts: 3,
  messageRate: 1.5,
  lastError: null,
}

const apiHealth: ApiHealth = {
  dashboardState: 'ok',
  agentInstances: 'pending',
  eventHistory: 'error',
}

const baseProps = {
  wsConnected: true,
  wsLastMessageTimestamp: '2026-01-01T12:00:00Z',
  wsDiagnostics,
  throughput: 1.5,
  pricesCount: 6,
  pricesFetched: true,
  apiHealth,
}

describe('ConnectionDiagnostics', () => {
  it('renders all 8 diagnostic rows', () => {
    render(<ConnectionDiagnostics {...baseProps} />)
    expect(screen.getByText('WebSocket Status')).toBeInTheDocument()
    expect(screen.getByText('API Base')).toBeInTheDocument()
    expect(screen.getByText('WebSocket URL')).toBeInTheDocument()
    expect(screen.getByText('Prices Source')).toBeInTheDocument()
    expect(screen.getByText('Message Rate')).toBeInTheDocument()
    expect(screen.getByText('Last Message')).toBeInTheDocument()
    expect(screen.getByText('Reconnect Attempts')).toBeInTheDocument()
    expect(screen.getByText('Last Error')).toBeInTheDocument()
  })

  it('shows connected badge with emerald when wsConnected', () => {
    render(<ConnectionDiagnostics {...baseProps} />)
    const wsValue = screen.getByText('● Connected')
    expect(wsValue.className).toContain('emerald-500')
  })

  it('shows disconnected with rose when ws down', () => {
    render(<ConnectionDiagnostics {...baseProps} wsConnected={false} />)
    const wsValue = screen.getByText('● Disconnected')
    expect(wsValue.className).toContain('rose-500')
  })

  it('shows 6 symbols (loaded) when pricesFetched', () => {
    render(<ConnectionDiagnostics {...baseProps} />)
    expect(screen.getByText(/6 symbols \(loaded\)/)).toBeInTheDocument()
  })

  it('shows (waiting) when prices not fetched', () => {
    render(<ConnectionDiagnostics {...baseProps} pricesFetched={false} pricesCount={0} />)
    expect(screen.getByText(/0 symbols \(waiting\)/)).toBeInTheDocument()
  })

  it('shows None for last error when null', () => {
    render(<ConnectionDiagnostics {...baseProps} />)
    expect(screen.getByText('None')).toBeInTheDocument()
  })

  it('shows last error message when present', () => {
    render(
      <ConnectionDiagnostics
        {...baseProps}
        wsDiagnostics={{ ...wsDiagnostics, lastError: 'connection refused' }}
      />,
    )
    expect(screen.getByText('connection refused')).toBeInTheDocument()
  })

  it('renders api health badges', () => {
    render(<ConnectionDiagnostics {...baseProps} />)
    expect(screen.getByText(/dashboard\/state: ok/i)).toBeInTheDocument()
    expect(screen.getByText(/agent-instances: pending/i)).toBeInTheDocument()
    expect(screen.getByText(/history\/events: error/i)).toBeInTheDocument()
  })

  it('formats throughput with 2 decimals msg/sec', () => {
    render(<ConnectionDiagnostics {...baseProps} throughput={2.5} />)
    expect(screen.getByText('2.50 msg/sec')).toBeInTheDocument()
  })

  it('shows reconnect attempts', () => {
    render(<ConnectionDiagnostics {...baseProps} />)
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})
