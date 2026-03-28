import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockStore = {
  wsConnected: false,
  killSwitchActive: false,
  setKillSwitch: vi.fn(),
  orders: [],
  positions: [],
  agentLogs: [],
  prices: {},
  systemMetrics: [],
  learningEvents: [],
  dashboardData: null
}

vi.mock('@/stores/useCodexStore', () => ({
  useCodexStore: () => mockStore
}))

vi.mock('@/components/EquityCurve', () => ({
  EquityCurve: () => null
}), { virtual: true })

vi.mock('@/components/MobileNavigation', () => ({
  MobileNavigation: () => null
}), { virtual: true })

import { DashboardView } from '@/app/dashboard/DashboardView'

describe('DashboardView — overview', () => {
  beforeEach(() => {
    mockStore.orders = []
    mockStore.positions = []
    mockStore.agentLogs = []
    mockStore.prices = {}
    mockStore.learningEvents = []
    mockStore.systemMetrics = []
    mockStore.dashboardData = null
  })

  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="overview" />)).not.toThrow()
  })

  it('shows mobile navigation labels', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText(/overview/i)).toBeInTheDocument()
    expect(screen.getByText(/trading/i)).toBeInTheDocument()
  })

  it('never shows NaN anywhere on screen', () => {
    render(<DashboardView section="overview" />)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })

  it('shows daily P&L on overview when empty', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText(/Daily P&L/i)).toBeInTheDocument()
  })

  it('shows ticker symbols on overview when empty', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText('BTC/USD')).toBeInTheDocument()
  })
})

describe('DashboardView — trading', () => {
  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="trading" />)).not.toThrow()
  })

  it('shows empty state when no positions', () => {
    render(<DashboardView section="trading" />)
    expect(screen.getByText(/no open positions/i)).toBeInTheDocument()
  })
})

describe('DashboardView — agents', () => {
  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="agents" />)).not.toThrow()
  })

  it('shows agents in waiting state when no logs', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText('SIGNAL_AGENT')).toBeInTheDocument()
    expect(screen.getAllByText('waiting')).toHaveLength(7)
  })
})
