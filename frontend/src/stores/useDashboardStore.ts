'use client'
import { create } from 'zustand'
import { createLogger } from '@/lib/logger'
import { api, API_ENDPOINTS } from '@/lib/apiClient'
import { coerceProposalContent, proposalStrategyName } from '@/lib/proposal-content'
import { normalizeClosedTrade, normalizeStoredNotification, normalizeTradeFeedItem } from './normalizers'
import type {
  AgentHeartbeat,
  ClosedTrade,
  AgentInstance,
  AgentLog,
  CachedPriceData,
  DailyPnl,
  DashboardData,
  LearningEvent,
  Notification,
  Order,
  PerformanceSummary,
  PnlSummary,
  Position,
  PriceRecord,
  Proposal,
  ProposalStatus,
  ProposalType,
  RecentEvent,
  StreamStat,
  SystemMetric,
  TradeFeedItem,
  WsDiagnostics,
} from './types'

// Single import surface: every consumer keeps importing domain types and
// normalizers from this module.
export * from './types'
export { normalizeClosedTrade, normalizeStoredNotification, normalizeTradeFeedItem } from './normalizers'

const log = createLogger('store')

type DashboardState = {
  prices: PriceRecord
  orders: Order[]
  positions: Position[]
  signals: Array<Record<string, unknown>>
  agentLogs: AgentLog[]
  riskAlerts: Array<Record<string, unknown>>
  notifications: Notification[]
  proposals: Proposal[]
  tradeFeed: TradeFeedItem[]
  closedTrades: ClosedTrade[]
  agentInstances: AgentInstance[]
  performanceSummary: PerformanceSummary | null
  pnlSummary: PnlSummary | null
  dailyPnl: DailyPnl[]
  learningEvents: LearningEvent[]
  systemMetrics: SystemMetric[]
  dashboardData: DashboardData | null
  isLoading: boolean
  regime: string
  killSwitchActive: boolean
  wsConnected: boolean
  marketTickCount: number
  lastMarketSymbol: string | null
  wsMessageCount: number
  wsLastMessageTimestamp: string | null
  wsDiagnostics: WsDiagnostics
  streamStats: Record<string, StreamStat>
  recentEvents: RecentEvent[]
  agentStatuses: AgentHeartbeat[]
  pipelineMetrics: Record<string, number>
  setAgentStatuses: (agents: AgentHeartbeat[]) => void
  setPipelineMetrics: (metrics: Record<string, number>) => void
  setTradeFeed: (trades: TradeFeedItem[]) => void
  addTradeFeedItem: (trade: TradeFeedItem) => void
  addClosedTrade: (trade: ClosedTrade) => void
  setAgentInstances: (instances: AgentInstance[]) => void
  setPerformanceSummary: (summary: PerformanceSummary) => void
  setDailyPnl: (pnl: DailyPnl[]) => void
  updatePrice: (symbol: string, price: number, change: number) => void
  updatePriceFromCache: (symbol: string, priceData: CachedPriceData) => void
  addSignal: (signal: Record<string, unknown>) => void
  addOrder: (order: Order) => void
  updateOrder: (order: Order) => void
  addAgentLog: (log: AgentLog) => void
  addRiskAlert: (alert: Record<string, unknown>) => void
  addNotification: (notification: unknown) => void
  addProposal: (proposal: Omit<Proposal, 'id' | 'status'> & { id?: string; status?: ProposalStatus }) => void
  updateProposalStatus: (id: string, status: ProposalStatus) => void
  addLearningEvent: (event: LearningEvent) => void
  addSystemMetric: (metric: SystemMetric) => void
  setDashboardData: (data: DashboardData | null) => void
  setLoading: (loading: boolean) => void
  setRegime: (regime: string) => void
  setKillSwitch: (active: boolean) => void
  setWsConnected: (connected: boolean) => void
  setWsDiagnostics: (diagnostics: Partial<WsDiagnostics>) => void
  trackWsMessage: (event: {
    stream?: string | null
    msgId?: string | null
    timestamp?: string | null
    symbol?: string | null
    price?: number | null
    change?: number | null
    eventType?: string | null
  }) => void
  trackMarketTick: (symbol?: string | null) => void
  hydrateDashboard: (data: DashboardData) => void
  hydrateFromLocalStorage: () => void
  bulkUpdate: (updates: Partial<DashboardState>) => void
  fetchPrices: () => Promise<void>
  fetchPositions: () => Promise<void>
  fetchPnl: () => Promise<void>
}

/** localStorage keys for the client-side display cache (REST re-hydrates anyway). */
const STORAGE_KEYS = {
  orders: 'dashboard.orders',
  positions: 'dashboard.positions',
  notifications: 'dashboard.notifications',
} as const

const _loadFromStorage = <T>(key: string, limit: number): T[] => {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as T[]).slice(0, limit) : []
  } catch {
    return []
  }
}

const _saveToStorage = (key: string, data: unknown[]): void => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, JSON.stringify(data))
  } catch {
    // quota exceeded or SSR — silently ignore
  }
}

// Initial state intentionally empty on BOTH server and client. localStorage
// hydration runs once on mount via `hydrateFromLocalStorage()` so the first
// client render matches the server-rendered HTML — preventing React
// hydration errors #418/#423/#425 that previously fired on every page load.
export const useDashboardStore = create<DashboardState>((set) => ({
  prices: {},
  orders: [],
  positions: [],
  signals: [],
  agentLogs: [],
  riskAlerts: [],
  notifications: [],
  proposals: [],
  tradeFeed: [],
  closedTrades: [],
  agentInstances: [],
  performanceSummary: null,
  pnlSummary: null,
  dailyPnl: [],
  learningEvents: [],
  systemMetrics: [],
  dashboardData: null,
  isLoading: true,
  regime: 'neutral',
  killSwitchActive: false,
  wsConnected: false,
  marketTickCount: 0,
  lastMarketSymbol: null,
  wsMessageCount: 0,
  wsLastMessageTimestamp: null,
  wsDiagnostics: { reconnectAttempts: 0, messageRate: 0, lastError: null },
  streamStats: {
    market_ticks: { count: 0, lastMessageTimestamp: null },
    signals: { count: 0, lastMessageTimestamp: null },
    orders: { count: 0, lastMessageTimestamp: null },
    executions: { count: 0, lastMessageTimestamp: null },
    agent_logs: { count: 0, lastMessageTimestamp: null },
    risk_alerts: { count: 0, lastMessageTimestamp: null },
    notifications: { count: 0, lastMessageTimestamp: null },
  },
  recentEvents: [],
  agentStatuses: [],
  pipelineMetrics: {},
  setAgentStatuses: (agentStatuses) => set({ agentStatuses }),
  setPipelineMetrics: (pipelineMetrics) => set({ pipelineMetrics }),
  setTradeFeed: (trades) => set((state) => {
    const normalized = (trades as unknown[])
      .filter((t): t is Record<string, unknown> => !!t && typeof t === 'object')
      .map(normalizeTradeFeedItem)
    const snapshotIds = new Set(normalized.map((t) => t.id))
    // Preserve WS-received trades that arrived after the last REST snapshot.
    const wsOnly = state.tradeFeed.filter((t) => !snapshotIds.has(t.id))
    return { tradeFeed: [...normalized, ...wsOnly].slice(0, 200) }
  }),
  addTradeFeedItem: (trade) => set((state) => {
    if (state.tradeFeed.some((t) => t.id === trade.id)) return state
    return { tradeFeed: [trade, ...state.tradeFeed].slice(0, 200) }
  }),
  // Live round-trip closes from the WS `trade_completed` stream. ClosedTrade
  // carries no id, so dedup on symbol + close time (the panel's row key); the
  // next snapshot replace reconciles wholesale. Cap matches the backend
  // mirror (REDIS_CLOSED_TRADES_MAX = 100).
  addClosedTrade: (trade) => set((state) => {
    const key = (t: ClosedTrade) => `${t.symbol}|${t.closed_at ?? ''}`
    if (state.closedTrades.some((t) => key(t) === key(trade))) return state
    return { closedTrades: [trade, ...state.closedTrades].slice(0, 100) }
  }),
  setAgentInstances: (agentInstances) => set({ agentInstances }),
  setPerformanceSummary: (performanceSummary) => set({ performanceSummary }),
  setDailyPnl: (dailyPnl) => set({ dailyPnl }),

  // Spread the existing entry first: WS price ticks carry no bid/ask, so they
  // must not wipe the L1 quote the REST poll hydrated (it refreshes next poll).
  updatePrice: (symbol, price, change) => set((state) => ({
    prices: {
      ...state.prices,
      [symbol]: {
        ...state.prices[symbol],
        price,
        change,
        previousPrice: state.prices[symbol]?.price ?? price - change,
        updatedAt: new Date().toISOString(),
      },
    }
  })),
  updatePriceFromCache: (symbol, priceData) => set((state) => ({
    prices: {
      ...state.prices,
      [symbol]: {
        ...state.prices[symbol],
        price: Number(priceData.price),
        change: 0, // Will be calculated based on previous price
        previousPrice: state.prices[symbol]?.price ?? Number(priceData.price),
        updatedAt: priceData.timestamp || new Date().toISOString(),
      },
    }
  })),
  fetchPrices: async () => {
    try {
      const response = await fetch(api("/dashboard/prices"))
      if (!response.ok) throw new Error('Failed to fetch prices')
      
      const data = await response.json()
      const prices: Record<string, CachedPriceData | null> = data.prices || {}
      
      set((state) => {
        const updatedPrices = { ...state.prices }
        for (const [symbol, priceData] of Object.entries(prices)) {
          if (priceData && typeof priceData === 'object') {
            const price = Number(priceData.price)
            // Skip entries where the API sent null/undefined/non-numeric price;
            // Number(undefined) = NaN which would poison the ticker display.
            if (!Number.isFinite(price)) continue
            const previousPrice = state.prices[symbol]?.price ?? price
            const change = price - previousPrice
            // Real L1 best bid/ask from the poller cache — kept only when the
            // quote is two-sided so the UI can never show a fake $0.00 side.
            const bid = Number(priceData.bid)
            const ask = Number(priceData.ask)
            const quote =
              Number.isFinite(bid) && bid > 0 && Number.isFinite(ask) && ask > 0
                ? { bid, ask }
                : {}

            updatedPrices[symbol] = {
              price,
              change,
              previousPrice,
              updatedAt: priceData.timestamp || new Date().toISOString(),
              ...quote,
            }
          }
        }
        return { prices: updatedPrices }
      })
    } catch (error) {
      log.error('Error fetching prices:', error)
    }
  },
  // Authoritative open positions from the PaperBroker-backed /positions endpoint.
  // Merge by symbol: REST is authoritative for symbols it returns; any WS-only
  // position for a symbol the endpoint doesn't cover is preserved.
  fetchPositions: async () => {
    try {
      const response = await fetch(api(API_ENDPOINTS.POSITIONS))
      if (!response.ok) return
      const data = await response.json()
      const incoming = Array.isArray(data.positions) ? (data.positions as Position[]) : []
      set((state) => {
        const restSymbols = new Set(incoming.map((p) => p.symbol))
        const merged = [
          ...incoming,
          ...state.positions.filter((p) => !restSymbols.has(p.symbol)),
        ]
        _saveToStorage(STORAGE_KEYS.positions, merged)
        return { positions: merged }
      })
    } catch (error) {
      log.error('Error fetching positions:', error)
    }
  },
  // Live realized + unrealized PnL breakdown from the PaperBroker-backed /pnl
  // endpoint. Stored separately from performanceSummary (which is the DB/trends
  // aggregate) so the UI can show broker-truth unrealized PnL in every mode.
  fetchPnl: async () => {
    try {
      const response = await fetch(api(API_ENDPOINTS.PNL))
      if (!response.ok) return
      const data = await response.json()
      const summary = data?.summary
      if (summary && typeof summary === 'object') {
        set({ pnlSummary: summary as PnlSummary })
      }
    } catch (error) {
      log.error('Error fetching pnl:', error)
    }
  },
  addSignal: (signal) => set((state) => ({
    signals: [signal, ...state.signals].slice(0, 50)
  })),
  addOrder: (order) => set((state) => {
    const next = [order, ...state.orders].slice(0, 100)
    _saveToStorage(STORAGE_KEYS.orders, next)
    return { orders: next }
  }),
  updateOrder: (order) => set((state) => {
    const next = state.orders.some((e) => e.order_id === order.order_id)
      ? state.orders.map((e) => e.order_id === order.order_id ? { ...e, ...order } : e)
      : [order, ...state.orders].slice(0, 100)
    _saveToStorage(STORAGE_KEYS.orders, next)
    return { orders: next }
  }),
  addAgentLog: (log) => set((state) => ({
    agentLogs: [log, ...state.agentLogs].slice(0, 100)
  })),
  addRiskAlert: (alert) => set((state) => ({
    riskAlerts: [alert, ...state.riskAlerts].slice(0, 50)
  })),
  addNotification: (notification) => set((state) => {
    const normalized = normalizeStoredNotification(notification)
    if (!normalized) return state
    if (state.notifications.some((n) => n.id === normalized.id)) return state
    // Cap matches the backend REDIS_NOTIFICATIONS_MAX (20) so the UI's
    // "max 20" label stays truthful and the list never grows unbounded.
    const next = [normalized, ...state.notifications].slice(0, 20)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEYS.notifications, JSON.stringify(next))
    }
    return { notifications: next }
  }),
  addProposal: (proposal) => set((state) => {
    // Derive a STABLE id from the backend identifiers so repeated REST polls
    // and WS broadcasts for the same proposal update it in place instead of
    // piling up duplicates. The approve/reject PATCH endpoint matches on this
    // id (the proposal's trace_id), so it MUST be the backend id — minting a
    // random one here both duplicated rows every poll and 404'd every vote.
    const stableId =
      (proposal.id != null && proposal.id !== '' ? String(proposal.id) : '') ||
      proposal.reflection_trace_id ||
      (proposal.trace_id != null ? String(proposal.trace_id) : '') ||
      `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const incomingStatus: ProposalStatus = proposal.status ?? 'pending'
    const existingIndex = state.proposals.findIndex((p) => p.id === stableId)
    if (existingIndex !== -1) {
      const existing = state.proposals[existingIndex]
      // Backend is the source of truth, but a later poll that still reports
      // "pending" must not clobber an approve/reject the operator just made
      // optimistically (the PATCH has already persisted it server-side).
      const status: ProposalStatus =
        incomingStatus === 'pending' && existing.status !== 'pending' ? existing.status : incomingStatus
      const next = [...state.proposals]
      next[existingIndex] = { ...existing, ...proposal, id: stableId, status }
      return { proposals: next }
    }
    return {
      proposals: [{ ...proposal, id: stableId, status: incomingStatus }, ...state.proposals].slice(0, 50),
    }
  }),
  updateProposalStatus: (id, status) => set((state) => ({
    proposals: state.proposals.map((p) => p.id === id ? { ...p, status } : p)
  })),
  addLearningEvent: (event) => set((state) => ({
    learningEvents: [event, ...state.learningEvents].slice(0, 50)
  })),
  addSystemMetric: (metric) => set((state) => ({
    systemMetrics: [
      metric,
      ...state.systemMetrics.filter((existing) => existing.metric_name !== metric.metric_name),
    ].slice(0, 100)
  })),
  setDashboardData: (data) => set({ dashboardData: data }),
  setLoading: (isLoading) => set({ isLoading }),
  setRegime: (regime) => set({ regime }),
  setKillSwitch: (killSwitchActive) => set({ killSwitchActive }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setWsDiagnostics: (diagnostics) => set((state) => ({
    wsDiagnostics: { ...state.wsDiagnostics, ...diagnostics }
  })),
  trackWsMessage: ({ stream, msgId, timestamp, symbol, price, change, eventType }) =>
    set((state) => {
      if (msgId && state.recentEvents.some((event) => event.msgId === msgId)) {
        return state
      }
      const resolvedStream = stream || 'system'
      const resolvedTimestamp = timestamp || new Date().toISOString()
      const existing = state.streamStats[resolvedStream] ?? { count: 0, lastMessageTimestamp: null }
      const event: RecentEvent = {
        stream: resolvedStream,
        msgId: msgId || 'n/a',
        timestamp: resolvedTimestamp,
        symbol: symbol ?? null,
        price: price ?? null,
        change: change ?? null,
        eventType: eventType ?? null,
      }
      return {
        wsMessageCount: state.wsMessageCount + 1,
        wsLastMessageTimestamp: resolvedTimestamp,
        wsDiagnostics: {
          ...state.wsDiagnostics,
          messageRate: Number((
            state.recentEvents.filter(
              (event) => Date.now() - new Date(event.timestamp).getTime() < 1000
            ).length + 1
          ).toFixed(2)),
        },
        streamStats: {
          ...state.streamStats,
          [resolvedStream]: {
            count: existing.count + 1,
            lastMessageTimestamp: resolvedTimestamp,
          },
        },
        recentEvents: [event, ...state.recentEvents].slice(0, 20),
      }
    }),
  trackMarketTick: (symbol) =>
    set((state) => ({
      marketTickCount: state.marketTickCount + 1,
      lastMarketSymbol: symbol || state.lastMarketSymbol,
    })),

  hydrateFromLocalStorage: () => {
    if (typeof window === 'undefined') return
    const orders = _loadFromStorage<Order>(STORAGE_KEYS.orders, 100)
    const positions = _loadFromStorage<Position>(STORAGE_KEYS.positions, 50)
    let notifications: Notification[] = []
    try {
      const raw = window.localStorage.getItem(STORAGE_KEYS.notifications)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          notifications = parsed
            .map(normalizeStoredNotification)
            .filter((item): item is Notification => item !== null)
            .slice(0, 20) // matches backend REDIS_NOTIFICATIONS_MAX
        }
      }
    } catch {
      // ignore parse errors
    }
    set((state) => ({
      orders: orders.length > 0 ? orders : state.orders,
      positions: positions.length > 0 ? positions : state.positions,
      notifications: notifications.length > 0 ? notifications : state.notifications,
    }))
  },
  hydrateDashboard: (data: DashboardData) => {
    set((currentState) => {
      const updates: Partial<DashboardState> = {
        dashboardData: data,
        isLoading: false
      }

      if (Array.isArray(data.system_metrics)) {
        updates.systemMetrics = [
          ...data.system_metrics,
          ...currentState.systemMetrics
        ].slice(0, 100)
      }

      if (Array.isArray(data.orders)) {
        // REST API sends side as "buy"/"sell" (OrderSide enum); store expects "long"/"short".
        // WS trade_fill path already normalizes in _handleTradeNotification — match it here.
        const normSide = (side: unknown): 'long' | 'short' => {
          const v = String(side ?? '').toLowerCase()
          return v === 'sell' || v === 'short' ? 'short' : 'long'
        }
        const restOrders = data.orders.map((o) => ({ ...o, side: normSide(o.side) }))
        updates.orders = [
          ...restOrders,
          ...currentState.orders.filter((order) =>
            !restOrders.some((newOrder) => newOrder.order_id === order.order_id)
          )
        ].slice(0, 100)
        _saveToStorage(STORAGE_KEYS.orders, updates.orders)
      }

      if (data.agent_logs) {
        const incomingLogs = (data.agent_logs as unknown[]).flatMap((raw) => {
          if (!raw || typeof raw !== 'object') return []
          const r = raw as Record<string, unknown>
          const agentName = String(r.agent_name || r.agent || r.source_agent || r.source || '')
          if (!agentName) return []
          const log: AgentLog = {
            agent_name: agentName,
            event_type: String(r.event_type || r.action || r.type || 'processed'),
            timestamp: String(r.timestamp || r.created_at || new Date().toISOString()),
            symbol: r.symbol as string | undefined,
            action: r.action as string | undefined,
            latency_ms: Number(r.latency_ms) || 0,
            primary_edge: r.primary_edge as string | undefined,
          }
          if (r.id != null) log.id = r.id as string | number
          if (r.message != null) log.message = String(r.message)
          if (r.trace_id != null) log.trace_id = String(r.trace_id)
          if (r.confidence != null) log.confidence = Number(r.confidence) || undefined
          if (r.stream) log.stream = r.stream
          if (r.message_id) log.message_id = r.message_id
          if (r.data) log.data = r.data
          return [log]
        })
        const logKey = (l: AgentLog) =>
          l.id != null ? String(l.id) : `${l.timestamp}|${l.agent_name}|${l.event_type}`
        const incomingKeys = new Set(incomingLogs.map(logKey))
        updates.agentLogs = [
          ...incomingLogs,
          ...currentState.agentLogs.filter((log) => !incomingKeys.has(logKey(log))),
        ].slice(0, 100)
      }

      if (Array.isArray(data.learning_events)) {
        updates.learningEvents = [
          ...data.learning_events,
          ...currentState.learningEvents.filter((event) =>
            !data.learning_events?.some((newEvent) => newEvent.id === event.id)
          )
        ].slice(0, 50)
      }

      if (Array.isArray(data.risk_alerts)) {
        updates.riskAlerts = [
          ...data.risk_alerts,
          ...currentState.riskAlerts.filter((alert) =>
            !data.risk_alerts?.some((newAlert) => newAlert.id === alert.id)
          )
        ].slice(0, 50)
      }

      if (Array.isArray(data.signals)) {
        updates.signals = [
          ...data.signals,
          ...currentState.signals.filter((signal) =>
            !data.signals?.some((newSignal) => newSignal.id === signal.id)
          )
        ].slice(0, 50)
      }

      if (Array.isArray(data.positions)) {
        // Merge by symbol: REST is authoritative for symbols it covers; keep WS-only positions.
        const restSymbols = new Set(data.positions.map((p) => p.symbol))
        const merged = [
          ...data.positions,
          ...currentState.positions.filter((p) => !restSymbols.has(p.symbol)),
        ]
        updates.positions = merged
        _saveToStorage(STORAGE_KEYS.positions, merged)
      }

      if (data.prices) {
        updates.prices = { ...currentState.prices, ...data.prices }
      }

      if (data.proposals && Array.isArray(data.proposals)) {
        const existingIds = new Set(currentState.proposals.map((p) => p.id))
        const newProposals = (data.proposals as Array<Record<string, unknown>>)
          .filter((p) => !existingIds.has(p.id as string))
          .map((p) => ({
            id: (p.id as string) ?? String(Date.now()),
            proposal_type: (p.proposal_type as ProposalType) ?? 'parameter_change' as ProposalType,
            // `content` may arrive as a structured object (e.g. challenger
            // promotions) — coerce to readable text so the row never shows
            // "[object Object]".
            content: coerceProposalContent(p.content),
            requires_approval: p.requires_approval !== false,
            confidence: typeof p.confidence === 'number' ? p.confidence : undefined,
            reflection_trace_id: p.reflection_trace_id as string | undefined,
            trace_id: (p.trace_id as string | undefined) ?? undefined,
            strategy_name:
              (p.strategy_name as string | undefined) ?? proposalStrategyName(p.content),
            grade_score: typeof p.grade_score === 'number' ? p.grade_score : null,
            timestamp: (p.timestamp as string) ?? new Date().toISOString(),
            // An applied record (ProposalApplier, same trace_id) means this is
            // done — never show it as pending awaiting a vote.
            status: p.applied === true
              ? ('approved' as ProposalStatus)
              : ((p.status as ProposalStatus) ?? ('pending' as ProposalStatus)),
            applied: p.applied === true,
            applied_at: (p.applied_at as string | null) ?? null,
          }))
        if (newProposals.length > 0) {
          updates.proposals = [...newProposals, ...currentState.proposals].slice(0, 50)
        }
      }

      // Closed trades: the REST snapshot is authoritative (already newest-first,
      // capped server-side), so replace wholesale rather than merging.
      if (Array.isArray(data.closed_trades)) {
        updates.closedTrades = (data.closed_trades as unknown[])
          .filter((t): t is Record<string, unknown> => !!t && typeof t === 'object')
          .map(normalizeClosedTrade)
      }

      if (data.trade_feed && Array.isArray(data.trade_feed)) {
        const normalized = (data.trade_feed as unknown[])
          .filter((t): t is Record<string, unknown> => !!t && typeof t === 'object')
          .map(normalizeTradeFeedItem)
        const existingTfIds = new Set(normalized.map((t) => t.id))
        const kept = currentState.tradeFeed.filter((t) => !existingTfIds.has(t.id))
        updates.tradeFeed = [...normalized, ...kept].slice(0, 200)
      }

      // Notifications hydrate from /dashboard/state so buy/sell fills survive
      // a page reload instead of only appearing on the live WebSocket stream.
      // Dedup is by Notification.id (backed by the stable notification_id from
      // the backend), so the REST snapshot and WS broadcast can't double up.
      if (data.notifications && Array.isArray(data.notifications)) {
        const normalized = data.notifications
          .map((n) => normalizeStoredNotification(n))
          .filter((n): n is Notification => n !== null)
        if (normalized.length > 0) {
          const seen = new Set<string>()
          const merged: Notification[] = []
          for (const n of [...normalized, ...currentState.notifications]) {
            if (seen.has(n.id)) continue
            seen.add(n.id)
            merged.push(n)
          }
          const next = merged.slice(0, 200)
          updates.notifications = next
          if (typeof window !== 'undefined') {
            window.localStorage.setItem(STORAGE_KEYS.notifications, JSON.stringify(next))
          }
        }
      }

      if (Array.isArray(data.agent_statuses)) {
        updates.agentStatuses = (data.agent_statuses as Array<Record<string, unknown>>)
          .filter((item) => typeof item?.name === 'string' && typeof item?.status === 'string') as unknown as AgentHeartbeat[]
      }

      return updates
    })
  },

  bulkUpdate: (updates: Partial<DashboardState>) => {
    set(updates)
  }
}))
