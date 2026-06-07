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
    updateProposalStatus: vi.fn(),
    setTradeFeed: vi.fn(),
    setAgentInstances: vi.fn(),
    setPerformanceSummary: vi.fn(),
    addProposal: vi.fn(),
    fetchPrices: vi.fn().mockResolvedValue(undefined),
    fetchPositions: vi.fn().mockResolvedValue(undefined),
    fetchPnl: vi.fn().mockResolvedValue(undefined),
    hydrateDashboard: vi.fn(),
  }
  // Honour an optional selector so slice-reading consumers (useLivePnl /
  // useLivePositions via useCodexStore((s) => s.orders)) get the slice, not the
  // whole store — matches the real zustand hook and DashboardView.test.
  const hook = Object.assign(
    (selector?: (s: typeof store) => unknown) =>
      typeof selector === 'function' ? selector(store) : store,
    { getState: () => store },
  )
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
  pool_name: 'SIGNAL_AGENT',
  status: 'active',
  started_at: new Date().toISOString(),
  retired_at: null,
  event_count: 42,
  uptime_seconds: 4980,
  ...overrides,
})

// The standalone Agent Instances panel was merged into the single Agent Status
// table — instance uptime is now folded into each agent's row, so there is one
// source of truth instead of two overlapping agent tables.
describe('Agent Status table — instance uptime merge', () => {
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

  it('renders the single Agent Status table (no separate instances panel)', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText('Agent Status')).toBeInTheDocument()
    expect(screen.queryByText(/no instances registered yet/i)).toBeNull()
  })

  it("folds an active instance's uptime into its agent row (4980s -> 1h 23m)", () => {
    mockStore.agentInstances = [makeInstance()]
    render(<DashboardView section="agents" />)
    expect(screen.getByText('1h 23m')).toBeInTheDocument()
  })

  it('ignores retired instances when showing uptime', () => {
    mockStore.agentInstances = [makeInstance({ status: 'retired', retired_at: new Date().toISOString() })]
    render(<DashboardView section="agents" />)
    expect(screen.queryByText('1h 23m')).toBeNull()
  })
})
