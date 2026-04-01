import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { TradeFeedItem } from '@/stores/useCodexStore'

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
    tradeFeed: [] as TradeFeedItem[],
    agentInstances: [],
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

const makeTrade = (overrides: Partial<TradeFeedItem> = {}): TradeFeedItem => ({
  id: 'trade-1',
  symbol: 'BTC/USD',
  side: 'buy',
  qty: 0.1,
  entry_price: 43000,
  exit_price: 43500,
  pnl: 50,
  pnl_percent: 1.16,
  order_id: 'order-1',
  execution_trace_id: 'trace-abc123def456',
  signal_trace_id: null,
  grade: null,
  grade_score: null,
  grade_label: null,
  status: 'filled',
  filled_at: new Date().toISOString(),
  graded_at: null,
  reflected_at: null,
  created_at: new Date().toISOString(),
  ...overrides,
})

describe('TradeFeed panel', () => {
  beforeEach(() => {
    mockStore.tradeFeed = []
    mockStore.agentInstances = []
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

  it('shows empty state when tradeFeed is empty', () => {
    render(<DashboardView section="trading" />)
    expect(screen.getByText(/no fills yet/i)).toBeInTheDocument()
  })

  it('renders symbol and side badge when store has items', () => {
    mockStore.tradeFeed = [makeTrade()]
    render(<DashboardView section="trading" />)
    expect(screen.getByText('BTC/USD')).toBeInTheDocument()
    expect(screen.getByText('BUY')).toBeInTheDocument()
  })

  it('shows positive P&L with green styling', () => {
    mockStore.tradeFeed = [makeTrade({ pnl: 50, pnl_percent: 1.16, side: 'buy' })]
    render(<DashboardView section="trading" />)
    const pnlEl = screen.getByText(/\+\$50\.00/)
    expect(pnlEl).toBeInTheDocument()
    expect(pnlEl.className).toMatch(/emerald/)
  })

  it('shows negative P&L with red styling', () => {
    mockStore.tradeFeed = [makeTrade({ pnl: -20, pnl_percent: -0.47, side: 'sell' })]
    render(<DashboardView section="trading" />)
    const pnlEl = screen.getByText(/-\$20\.00/)
    expect(pnlEl).toBeInTheDocument()
    expect(pnlEl.className).toMatch(/rose/)
  })

  it('renders grade badge when grade is set', () => {
    mockStore.tradeFeed = [makeTrade({ grade: 'A' })]
    render(<DashboardView section="trading" />)
    expect(screen.getByText('A')).toBeInTheDocument()
  })

  it('trace chip renders as a clickable button element', () => {
    // execution_trace_id = 'abcdef12-9999-0000-1111-222233334444'
    // chip text: trace:{first 8 chars}… = "trace:abcdef12…"
    const tradeWithTrace = makeTrade({ execution_trace_id: 'abcdef12-9999-0000-1111-222233334444' })
    mockStore.tradeFeed = [tradeWithTrace]
    render(<DashboardView section="trading" />)
    const traceBtn = screen.getByText(/trace:abcdef12/)
    expect(traceBtn).toBeInTheDocument()
    expect(traceBtn.tagName).toBe('BUTTON')
  })
})
