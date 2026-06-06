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
    expect(screen.getByText(/Total P&L/i)).toBeInTheDocument()
  })

  it('never shows NaN anywhere on screen', () => {
    render(<DashboardView section="overview" />)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })

  it('shows the Total P&L headline on overview when empty', () => {
    render(<DashboardView section="overview" />)
    expect(screen.getByText(/Total P&L/i)).toBeInTheDocument()
  })

  it('shows a live Total P&L = realized orders + mark-to-market unrealized', () => {
    // Regression: the overview P&L was realized-only and frozen. It now combines
    // realized fills with live mark-to-market unrealized. The position carries a
    // stale stored pnl: 0, but current_price 130 vs entry 100 on qty 1 marks to
    // +$30 unrealized, proving the value is recomputed from price, not trusted.
    mockStore.orders = [{ status: 'filled', pnl: 10 }]
    mockStore.positions = [
      { symbol: 'BTC/USD', side: 'long', quantity: 1, entry_price: 100, current_price: 130, pnl: 0 },
    ]

    render(<DashboardView section="overview" />)

    // realized $10 + unrealized $30 = $40. The +$40.00 now appears both in the
    // headline tile and as the live equity curve's endpoint (its Net == current
    // total P&L) — both are correct, so assert it renders rather than that it is
    // unique.
    expect(screen.getByText('Total P&L')).toBeInTheDocument()
    expect(screen.getAllByText('+$40.00').length).toBeGreaterThan(0)
    // Breakdown renders as labelled mini-stats ("Realized"/"Unrealized" are
    // distinct from the Performance card's "Realized P&L").
    expect(screen.getByText('Realized')).toBeInTheDocument()
    expect(screen.getByText('Unrealized')).toBeInTheDocument()
  })

  it('Daily Change % reflects live unrealized P&L, not realized-only (no longer frozen at 0.00%)', () => {
    // Regression: Daily Change came from realized order PnL only, so it read 0.00%
    // while an open position was underwater — contradicting the Total P&L tile. It
    // now uses the live total P&L (realized + mark-to-market unrealized) over the
    // equity base, so it moves with the market and agrees in sign with Total P&L.
    mockStore.orders = []
    mockStore.positions = [
      { symbol: 'BTC/USD', side: 'long', quantity: 100, entry_price: 100, current_price: 100, pnl: 0 },
    ]
    // Live price marks the position down: (90 - 100) * 100 = -1000 unrealized.
    mockStore.prices = { 'BTC/USD': { price: 90, updatedAt: new Date().toISOString() } }

    render(<DashboardView section="overview" />)

    // -1000 / 100_000 (default paper equity) * 100 = -1.00%. The old realized-only
    // logic would have shown 0.00% here.
    expect(screen.getByText('-1.00%')).toBeInTheDocument()
  })

  it('explains tiny positive best trade values on overview', () => {
    mockStore.performanceSummary = {
      total_pnl: -5,
      win_rate: 0.5,
      best_trade: 0.01,
      worst_trade: -6,
    }

    render(<DashboardView section="overview" />)

    expect(screen.getByTestId('best-trade-tiny-explanation')).toHaveTextContent(/tiny gains \(for example \+\$0.01\) are valid execution data\./i)
    expect(screen.getByTestId('best-trade-tiny-explanation')).toHaveTextContent(/From API trade history aggregate;/i)
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

    expect(screen.getByTestId('best-trade-tiny-explanation')).toHaveTextContent(/From 2 closed trades;/i)
  })

  it('does not show explanation when best trade is not tiny-positive', () => {
    mockStore.performanceSummary = {
      total_pnl: 12,
      win_rate: 0.5,
      best_trade: 0.25,
      worst_trade: -1,
    }

    render(<DashboardView section="overview" />)

    expect(screen.queryByTestId('best-trade-tiny-explanation')).not.toBeInTheDocument()
  })

  it('does not show explanation at threshold boundary (+$0.05)', () => {
    mockStore.performanceSummary = {
      total_pnl: 5,
      win_rate: 0.6,
      best_trade: 0.05,
      worst_trade: -1,
    }

    render(<DashboardView section="overview" />)

    expect(screen.queryByTestId('best-trade-tiny-explanation')).not.toBeInTheDocument()
  })

  it('does not show explanation when no performance summary source exists', () => {
    mockStore.performanceSummary = null
    mockStore.orders = []
    mockStore.dashboardData = null

    render(<DashboardView section="overview" />)

    expect(screen.queryByTestId('best-trade-tiny-explanation')).not.toBeInTheDocument()
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

  it('surfaces the open position on the overview so the Active Positions count has visible detail', () => {
    // Regression: the overview showed an "Active Positions: 1" KPI but no
    // positions list anywhere on the page, so operators saw the count and could
    // not find the position. The Open Positions table now lives on the overview.
    mockStore.positions = [
      {
        symbol: 'BTC/USD',
        side: 'long',
        quantity: 0.25,
        entry_price: 50000,
        current_price: 50100,
        pnl: 25,
        pnl_percent: 0.2,
      },
    ]

    render(<DashboardView section="overview" />)

    expect(screen.getByText('Open Positions')).toBeInTheDocument()
    // Side badge + entry price are unique to the position row (the ticker grid
    // reuses BTC/USD but never renders "LONG" or the entry price).
    expect(screen.getByText('LONG')).toBeInTheDocument()
    expect(screen.getByText('$50,000.00')).toBeInTheDocument()
  })

  it('excludes flat (qty 0) positions from the overview Open Positions table', () => {
    // The table and the "Active Positions" KPI share isActivePosition, so a flat
    // row is counted nowhere and listed nowhere — they can never disagree.
    mockStore.positions = [
      { symbol: 'BTC/USD', side: 'long', quantity: 0, entry_price: 50000, current_price: 50100, pnl: 0 },
    ]

    render(<DashboardView section="overview" />)

    expect(screen.getByText('Open Positions')).toBeInTheDocument()
    expect(screen.getByText(/no open positions/i)).toBeInTheDocument()
    expect(screen.queryByText('LONG')).not.toBeInTheDocument()
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

  it('shows the pipeline, KPIs, diagnostics and empty state when no agent wiring data is available', () => {
    render(<DashboardView section="agents" />)
    expect(screen.getByText(/Agent Pipeline/i)).toBeInTheDocument()
    expect(screen.getByText(/Agents Online/i)).toBeInTheDocument()
    expect(screen.getByText(/System Diagnostics/i)).toBeInTheDocument()
    expect(screen.getByText(/Heartbeats \(in-memory\/Redis\)/i)).toBeInTheDocument()
    expect(screen.getByText(/No instances registered yet/i)).toBeInTheDocument()
  })

  it('does not count agent lifecycle (spawn) logs as produced events', () => {
    // Regression: an agent coming online writes an agent_log with
    // log_type="lifecycle". Counting it made idle learning agents read "1 event"
    // while the Cognitive Engine correctly showed 0. Only the real (grade) log
    // should be counted.
    mockStore.agentLogs = [
      { agent_name: 'STRATEGY_PROPOSER', log_type: 'lifecycle', message: 'lifecycle', timestamp: new Date().toISOString() },
      { agent_name: 'GRADE_AGENT', log_type: 'grade', message: 'scored', timestamp: new Date().toISOString() },
    ]
    render(<DashboardView section="agents" />)
    // Exactly one Agent Status row shows an event count — Grade's real output.
    // The proposer's only log was a spawn, so it is not counted (renders "—").
    const eventCells = screen.getAllByText(
      (_, el) => el?.tagName === 'TD' && /^\d+ events$/.test(el.textContent ?? ''),
    )
    expect(eventCells).toHaveLength(1)
    expect(eventCells[0].textContent).toBe('1 events')
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
    // "Signal Agent" and "Live" now appear in BOTH the pipeline and the status
    // table — same label in both places, which is the point (uniform names).
    expect(screen.getAllByText('Signal Agent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Live').length).toBeGreaterThan(0)
    expect(screen.getByText('Realtime')).toBeInTheDocument()
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

  it('always registers the full agent roster, even before any agent reports', () => {
    // Notification / Challenger / Proposal Applier are roster members that are
    // NOT pipeline stages, so they only appear via the status-table backfill.
    // Seeing them with an empty store proves every documented agent is wired in.
    render(<DashboardView section="agents" />)
    expect(screen.getByText('Proposal Applier')).toBeInTheDocument()
    expect(screen.getByText('Notification Agent')).toBeInTheDocument()
    expect(screen.getByText('Challenger Agent')).toBeInTheDocument()
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
