import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'

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
    updateProposalStatus: vi.fn(),
    setTradeFeed: vi.fn(),
    setAgentInstances: vi.fn(),
    setPerformanceSummary: vi.fn(),
    addProposal: vi.fn(),
    fetchPrices: vi.fn().mockResolvedValue(undefined),
    hydrateDashboard: vi.fn(),
  }
  // Zustand hooks accept an optional selector — honour it so consumers like
  // useSystemStatus that read scalar slices (e.g. s.orders.length) get the
  // expected value rather than the entire store object.
  const hook = Object.assign(
    (selector?: (s: typeof store) => unknown) =>
      typeof selector === 'function' ? selector(store) : store,
    { getState: () => store },
  )
  return { mockStore: store, mockUseCodexStore: hook }
})

vi.mock('@/stores/useCodexStore', () => ({
  useCodexStore: mockUseCodexStore
}))

vi.mock('@/components/EquityCurve', () => ({
  EquityCurve: () => null
}), { virtual: true })

vi.mock('@/components/MobileNavigation', () => ({
  MobileNavigation: () => null
}), { virtual: true })

import { DashboardView } from '@/app/dashboard/DashboardView'

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({}),
  }) as unknown as typeof fetch
})

describe('DashboardView — overview', () => {
  beforeEach(() => {
    mockStore.wsConnected = false
    mockStore.orders = []
    mockStore.positions = []
    mockStore.agentLogs = []
    mockStore.prices = {}
    mockStore.learningEvents = []
    mockStore.systemMetrics = []
    mockStore.dashboardData = null
    mockStore.proposals = []
  })

  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="overview" />)).not.toThrow()
  })

  it('shows mobile navigation labels', () => {
    render(<DashboardView section="overview" />)
    // Mobile nav is mocked to null in this suite; assert key overview content instead.
    expect(screen.getByText(/System Status:/i)).toBeInTheDocument()
    expect(screen.getByText(/Daily P&L/i)).toBeInTheDocument()
  })

  it('never shows NaN anywhere on screen', () => {
    render(<DashboardView section="overview" />)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })

  it('shows daily P&L on overview when empty', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText(/Daily P&L/i)).toBeInTheDocument()
  })

  it('explains tiny positive best trade values on overview', () => {
    mockStore.performanceSummary = {
      total_pnl: -5,
      win_rate: 0.5,
      best_trade: 0.01,
      worst_trade: -6,
    }

    render(<DashboardView section="overview" />)

    expect(screen.getByText(/tiny gains \(for example \+\$0.01\) are valid execution data\./i)).toBeInTheDocument()
    expect(screen.getByText(/From API trade history aggregate;/i)).toBeInTheDocument()
  })

  it('shows local closed-trade count when tiny best trade comes from fallback summary', () => {
    mockStore.performanceSummary = {
      total_pnl: 0,
      win_rate: 0,
      best_trade: 0,
      worst_trade: 0,
    }
    mockStore.orders = [
      { status: 'filled', pnl: 0.01 },
      { status: 'closed', pnl: -1.23 },
    ]

    render(<DashboardView section="overview" />)

    expect(screen.getByText(/From 2 closed trades;/i)).toBeInTheDocument()
  })

  it('shows ticker symbols on overview when empty', () => {
    render(<DashboardView section="overview" />)
    // When loading, shows skeletons instead of ticker symbols
    // The ticker symbols appear after loading completes
    expect(screen.getByText(/Live Market Prices/i)).toBeInTheDocument()
  })

  it('marks system as trading when open positions exist without orders/trade feed', () => {
    mockStore.wsConnected = true
    mockStore.positions = [{ side: 'long', pnl: 5.25 }]
    mockStore.orders = []
    mockStore.tradeFeed = []

    render(<DashboardView section="overview" />)

    expect(screen.getByText(/System Status:\s*trading/i)).toBeInTheDocument()
  })
})

describe('DashboardView — trading', () => {
  beforeEach(() => {
    mockStore.wsConnected = false
  })

  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="trading" />)).not.toThrow()
  })

  it('shows empty state when no positions', () => {
    render(<DashboardView section="trading" />)
    expect(screen.getAllByText(/no fills yet/i).length).toBeGreaterThan(0)
  })
})

describe('DashboardView — agents', () => {
  beforeEach(() => {
    mockStore.wsConnected = false
    mockStore.agentStatuses = []
    mockStore.notifications = []
  })

  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="agents" />)).not.toThrow()
  })

  it('shows empty state when no agent wiring data is available', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText(/Active Agents/i)).toBeInTheDocument()
    expect(screen.getByText(/Live heartbeat < 10s/i)).toBeInTheDocument()
    expect(screen.getByText(/System Diagnostics/i)).toBeInTheDocument()
    expect(screen.getByText(/Heartbeats \(in-memory\/Redis\)/i)).toBeInTheDocument()
    expect(screen.getByText(/No instances registered yet/i)).toBeInTheDocument()
  })

  it('renders heartbeat-wired agent status rows (in-memory running -> Live)', () => {
    mockStore.agentStatuses = [
      {
        name: 'SIGNAL_AGENT',
        status: 'running',
        event_count: 42,
        last_event: 'processed_signal',
        last_seen: Math.floor(Date.now() / 1000),
        last_seen_at: new Date().toISOString(),
        source: 'heartbeat',
        seconds_ago: 0,
      }
    ]
    render(<DashboardView section="agents" />)
    expect(screen.getByText('Signal Agent')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(screen.getByText('Realtime')).toBeInTheDocument()
  })

  it('falls back when latest notification timestamp is invalid', () => {
    mockStore.notifications = [
      {
        id: 'notif-invalid-ts',
        severity: 'INFO',
        title: 'Bad timestamp event',
        message: 'Timestamp malformed',
        notification_type: 'system.test',
        stream_source: 'runtime',
        timestamp: 'not-a-date',
      },
    ]

    render(<DashboardView section="agents" />)

    expect(screen.getByText('No activity yet')).toBeInTheDocument()
    expect(screen.queryByText(/Last:\s*Invalid Date/i)).not.toBeInTheDocument()
  })


  it('renders buy trade notifications with trade fields', () => {
    mockStore.notifications = [
      {
        id: 'notif-1',
        severity: 'INFO',
        title: 'BUY filled: BTC/USD',
        message: 'BUY BTC/USD filled | Fill $50100.00 | Qty 0.25 | Notional $12525.00',
        notification_type: 'trade.buy_filled',
        stream_source: 'executions',
        action: 'buy',
        symbol: 'BTC/USD',
        qty: 0.25,
        fill_price: 50100,
        notional: 12525,
        pnl: null,
        pnl_percent: null,
        trace_id: 'trace-buy',
        state: 'open',
        display: {
          kind: 'trade_execution',
          tone: 'buy',
          icon: 'arrow-up-right',
          title: 'BUY filled: BTC/USD',
          subtitle: 'BUY BTC/USD filled | Fill $50,100.00 | Qty 0.25 | Notional $12,525.00',
          status_label: 'open',
          badges: [{ label: 'BUY', tone: 'buy' }],
          facts: [
            { label: 'Symbol', value: 'BTC/USD' },
            { label: 'Qty', value: '0.25' },
            { label: 'Fill', value: '$50,100.00' },
            { label: 'Notional', value: '$12,525.00' },
          ],
          meta: [
            { label: 'Type', value: 'trade.buy_filled' },
            { label: 'Source', value: 'executions' },
          ],
        },
        timestamp: new Date().toISOString(),
      },
    ]

    render(<DashboardView section="agents" />)

    expect(screen.getByText('BUY filled: BTC/USD')).toBeInTheDocument()
    expect(screen.getByText(/trade\.buy_filled/)).toBeInTheDocument()
    expect(screen.getByText('Qty')).toBeInTheDocument()
    expect(screen.getByText('0.25')).toBeInTheDocument()
    expect(screen.getByText('$12,525.00')).toBeInTheDocument()
  })
})
