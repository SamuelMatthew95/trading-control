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
    fetchPositions: vi.fn().mockResolvedValue(undefined),
    fetchPnl: vi.fn().mockResolvedValue(undefined),
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

describe('DashboardView — overview (trading terminal)', () => {
  beforeEach(() => {
    mockStore.wsConnected = false
    mockStore.orders = []
    mockStore.positions = []
    mockStore.agentLogs = []
    mockStore.prices = {}
    mockStore.tradeFeed = []
    mockStore.learningEvents = []
    mockStore.systemMetrics = []
    mockStore.dashboardData = null
    mockStore.proposals = []
  })

  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="overview" />)).not.toThrow()
  })

  it('renders the real, read-only terminal panels', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText('Watchlist')).toBeInTheDocument()
    expect(screen.getByText('Positions')).toBeInTheDocument()
    expect(screen.getByText('Agent Decisions')).toBeInTheDocument()
    expect(screen.getByText('Executions')).toBeInTheDocument()
  })

  it('has no manual order-entry surface — agents place orders', () => {
    render(<DashboardView section="overview" />)
    expect(screen.queryByText('Order Ticket')).not.toBeInTheDocument()
    expect(screen.queryByText('Order Book')).not.toBeInTheDocument()
  })

  it('lists the real monitored symbols (crypto + equities)', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getAllByText('BTC/USD').length).toBeGreaterThan(0)
    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SOL/USD').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TSLA').length).toBeGreaterThan(0)
  })

  it('does not list symbols the price poller never polls', () => {
    // REGRESSION: NVDA/MSFT/GOOGL are in VALID_SYMBOLS (broker-side validation)
    // but have no price feed — showing them pinned a fabricated constant price
    // at +0.00% forever. The watchlist universe is exactly the polled set.
    render(<DashboardView section="overview" />)
    expect(screen.queryByText('NVDA')).not.toBeInTheDocument()
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument()
    expect(screen.queryByText('GOOGL')).not.toBeInTheDocument()
  })

  it('shows honest empty states when the account is flat', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText('No open positions')).toBeInTheDocument()
    expect(screen.getByText('No agent decisions yet')).toBeInTheDocument()
    expect(screen.getByText('No fills yet')).toBeInTheDocument()
  })

  it('never shows NaN anywhere on screen', () => {
    render(<DashboardView section="overview" />)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
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



describe('DashboardView — learning', () => {
  beforeEach(() => {
    mockStore.tradeFeed = []
    mockStore.proposals = []
    mockStore.agentLogs = []
    mockStore.performanceSummary = null
  })

  it('renders a cohesive learning control plane without legacy calibration panels', () => {
    render(<DashboardView section="learning" />)

    expect(screen.getByText('Learning Control Plane')).toBeInTheDocument()
    expect(screen.getByText('Graded Trade Outcomes')).toBeInTheDocument()
    expect(screen.getByText('Proposal Outcomes')).toBeInTheDocument()
    expect(screen.queryByText(/Move Distribution/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Strategy Lifecycle/i)).not.toBeInTheDocument()
  })
})

describe('DashboardView — agents', () => {
  beforeEach(() => {
    mockStore.wsConnected = false
    mockStore.agentStatuses = []
    mockStore.notifications = []
    mockStore.agentLogs = []
    mockStore.agentInstances = []
    mockStore.orders = []
    mockStore.proposals = []
    mockStore.marketTickCount = 0
    mockStore.lastMarketSymbol = null
  })

  it('renders without crashing when store is empty', () => {
    expect(() => render(<DashboardView section="agents" />)).not.toThrow()
  })

  it('shows the pipeline, KPIs, diagnostics and scorecards when no agent wiring data is available', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText(/Agent Pipeline/i)).toBeInTheDocument()
    expect(screen.getByText(/Agents Online/i)).toBeInTheDocument()
    expect(screen.getByText(/System Diagnostics/i)).toBeInTheDocument()
    expect(screen.getByText(/Heartbeats \(in-memory\/Redis\)/i)).toBeInTheDocument()
    // The scorecards are the single per-agent view — the redundant Agent Status
    // table ("Live · Hybrid" rows) was removed.
    expect(screen.getByText('Agent Scorecards')).toBeInTheDocument()
    expect(screen.queryByText('Agent Status')).toBeNull()
  })

  it('does not count agent lifecycle (spawn) logs as produced events', () => {
    // Regression: an agent coming online writes an agent_log with
    // log_type="lifecycle". Counting it made idle learning agents read as live
    // while the Cognitive Engine correctly showed 0. Only the real (grade) log
    // should be counted.
    mockStore.agentLogs = [
      { agent_name: 'STRATEGY_PROPOSER', log_type: 'lifecycle', message: 'lifecycle', timestamp: new Date().toISOString() },
      { agent_name: 'GRADE_AGENT', log_type: 'grade', message: 'scored', timestamp: new Date().toISOString() },
    ]
    render(<DashboardView section="agents" />)
    // Exactly one pipeline stage reads Live — Grade's real output. The
    // proposer's only log was a spawn, so it is not counted (stays Waiting).
    expect(screen.getAllByText('Live')).toHaveLength(1)
    expect(screen.getByText(/Agents Online/i)).toBeInTheDocument()
  })

  it('renders heartbeat-wired agents as Live in the pipeline', () => {
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
    expect(screen.getAllByText('Signal Agent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Live').length).toBeGreaterThan(0)
  })

  it('keeps an agent Live while its heartbeat is within the backend 2-min window', () => {
    // A 30s-old heartbeat is healthy per the backend contract
    // (AGENT_STALE_THRESHOLD_SECONDS = 120). The previous 10s window wrongly
    // painted it "Stale", contradicting the active Agent Instances table.
    const thirtySecondsAgo = Date.now() - 30_000
    mockStore.agentStatuses = [
      {
        name: 'SIGNAL_AGENT',
        status: 'running',
        event_count: 42,
        last_event: 'processed_signal',
        last_seen: Math.floor(thirtySecondsAgo / 1000),
        last_seen_at: new Date(thirtySecondsAgo).toISOString(),
        source: 'heartbeat',
        seconds_ago: 30,
      },
    ]
    render(<DashboardView section="agents" />)
    expect(screen.getAllByText('Live').length).toBeGreaterThan(0)
    expect(screen.queryByText('Stale')).not.toBeInTheDocument()
  })

  // NOTE: full-roster coverage ("every documented agent appears even before it
  // reports") moved with the roster surface: the backend payload grades every
  // ALL_AGENT_NAMES member (tests/api/test_agent_performance.py) and the
  // scorecards render one card per payload agent (AgentScorecards.test.tsx).

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

    // The title now appears in both the Live Activity timeline and the
    // Notification feed — the aggregated story re-surfaces the same event.
    expect(screen.getAllByText('BUY filled: BTC/USD').length).toBeGreaterThan(0)
    expect(screen.getByText(/trade\.buy_filled/)).toBeInTheDocument()
    expect(screen.getByText('Qty')).toBeInTheDocument()
    expect(screen.getByText('0.25')).toBeInTheDocument()
    expect(screen.getByText('$12,525.00')).toBeInTheDocument()
  })
})

describe('DashboardView — theming (light/dark duality)', () => {
  // The section frame (root wrapper + SectionHeader) is shared by EVERY section,
  // so a dark-only class here breaks light mode on every page at once. Guard the
  // base (non-`dark:`) tokens so the redesign's dark "console" tone can only live
  // behind a `dark:` variant — never as the bare, theme-agnostic class.
  const baseTokens = (className: string): string[] =>
    className.split(/\s+/).filter((token) => token.length > 0 && !token.startsWith('dark:'))

  const hasDarkSurface = (tokens: string[]): boolean =>
    tokens.some((token) => /^bg-slate-(800|900|950)(\/\d+)?$/.test(token))

  beforeEach(() => {
    mockStore.wsConnected = false
    mockStore.agentStatuses = []
    mockStore.agentLogs = []
    mockStore.agentInstances = []
    mockStore.notifications = []
    mockStore.proposals = []
  })

  it('renders the root content wrapper with a light background base (dark only behind dark:)', () => {
    const { container } = render(<DashboardView section="agents" />)
    const root = container.firstChild as HTMLElement
    const tokens = baseTokens(root.className)
    expect(tokens).toContain('bg-slate-100')
    expect(tokens).toContain('text-slate-900')
    expect(hasDarkSurface(tokens)).toBe(false)
    expect(root.className).toContain('dark:bg-slate-950')
  })

  it('renders the section header as a light panel with a readable title in light mode', () => {
    render(<DashboardView section="agents" />)
    const title = screen.getByRole('heading', { name: /Agent health and production activity/i })
    const titleTokens = baseTokens(title.className)
    // Bare `text-white` is invisible on the light panel — the bug we are guarding.
    expect(titleTokens).toContain('text-slate-900')
    expect(titleTokens).not.toContain('text-white')
    expect(title.className).toContain('dark:text-white')

    const header = title.closest('section') as HTMLElement
    const headerTokens = baseTokens(header.className)
    expect(headerTokens).toContain('bg-white')
    expect(hasDarkSurface(headerTokens)).toBe(false)
    expect(header.className).toContain('dark:bg-slate-950/90')
  })
})

describe('DashboardView — backend offline', () => {
  beforeEach(() => {
    mockStore.wsConnected = false
    mockStore.orders = []
    mockStore.tradeFeed = []
    mockStore.notifications = []
    mockStore.dashboardData = null
    // Every REST endpoint unreachable — drives useRestPoll's backendOffline flag
    // through the real hook rather than stubbing it.
    global.fetch = vi.fn().mockRejectedValue(new Error('backend down')) as unknown as typeof fetch
  })

  it('keeps last-known panels and shows the dismissible banner when data was loaded', async () => {
    mockStore.dashboardData = { mode: 'in_memory' } // something loaded this session
    render(<DashboardView section="overview" />)
    expect(await screen.findByText(/Backend unreachable — showing last known data/)).toBeInTheDocument()
    // The panels behind the banner keep rendering last-known values.
    expect(screen.getByText('Watchlist')).toBeInTheDocument()
  })

  it('swaps content for the explanatory empty state when nothing was ever loaded', async () => {
    render(<DashboardView section="overview" />)
    expect(await screen.findByText('Backend offline — no data received yet')).toBeInTheDocument()
    expect(screen.queryByText('Watchlist')).not.toBeInTheDocument()
  })
})
