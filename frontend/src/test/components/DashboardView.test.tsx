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

  it('shows empty state when no agents', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText(/no agent data available/i)).toBeInTheDocument()
  })

  it('shows empty state when no prices', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText(/no live price data/i)).toBeInTheDocument()
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

  it('shows empty state when no agent logs', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText(/no agent data available/i)).toBeInTheDocument()
  })
})
