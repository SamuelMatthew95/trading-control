import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { AgentInstance } from '@/stores/useCodexStore'

const { mockStore, mockUseCodexStore } = vi.hoisted(() => {
  const store: Record<string, unknown> = {
    wsConnected: false,
    killSwitchActive: false,
    setKillSwitch: vi.fn(),
    orders: [],
    positions: [],
    agentLogs: [],
    prices: {},
    systemMetrics: [],
    learningEvents: [],
    dashboardData: null,
    proposals: [],
    tradeFeed: [],
    agentInstances: [] as AgentInstance[],
    performanceSummary: null,
    dailyPnl: [],
    notifications: [],
    recentEvents: [],
    streamStats: {},
    agentStatuses: [],
    marketTickCount: 0,
    lastMarketSymbol: null,
    wsMessageCount: 0,
    wsLastMessageTimestamp: null,
    acknowledgeNotification: vi.fn(),
    updateProposalStatus: vi.fn(),
    setTradeFeed: vi.fn(),
    setAgentInstances: vi.fn(),
    setPerformanceSummary: vi.fn(),
    addProposal: vi.fn(),
    fetchPrices: vi.fn().mockResolvedValue(undefined),
  }
  const hook = Object.assign(() => store, { getState: () => store })
  return { mockStore: store, mockUseCodexStore: hook }
})

vi.mock('@/stores/useCodexStore', () => ({
  useCodexStore: mockUseCodexStore,
}))

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({}),
  }) as unknown as typeof fetch
})

import { DashboardView } from '@/app/dashboard/DashboardView'

const makeInstance = (overrides: Partial<AgentInstance> = {}): AgentInstance => ({
  id: 'inst-1',
  instance_key: 'signal_agent_pool_0',
  pool_name: 'signal_pool',
  status: 'active',
  started_at: new Date().toISOString(),
  retired_at: null,
  event_count: 42,
  uptime_seconds: 4980,
  ...overrides,
})

describe('AgentInstances panel', () => {
  beforeEach(() => {
    mockStore.agentInstances = []
    mockStore.tradeFeed = []
    mockStore.performanceSummary = null
    mockStore.orders = []
    mockStore.positions = []
    mockStore.agentLogs = []
    mockStore.prices = {}
    mockStore.learningEvents = []
    mockStore.systemMetrics = []
    mockStore.dashboardData = null
    mockStore.proposals = []
  })

  it('renders empty state when agentInstances is empty', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText(/no instances registered yet/i)).toBeInTheDocument()
  })

  it('shows green dot and event count for an active instance', () => {
    mockStore.agentInstances = [makeInstance()]
    render(<DashboardView section="agents" />)
    expect(screen.getByText('signal_agent_pool_0')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    // active status label
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('shows retired status for a retired instance', () => {
    mockStore.agentInstances = [makeInstance({ status: 'retired', retired_at: new Date().toISOString() })]
    render(<DashboardView section="agents" />)
    expect(screen.getByText('retired')).toBeInTheDocument()
  })

  it('formats uptime as hours and minutes style', () => {
    // 4980 seconds = 1h 23m
    mockStore.agentInstances = [makeInstance({ uptime_seconds: 4980 })]
    render(<DashboardView section="agents" />)
    expect(screen.getByText('1h 23m')).toBeInTheDocument()
  })
})
