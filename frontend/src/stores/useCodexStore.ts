'use client'
import { create } from 'zustand'
import { api } from '@/lib/apiClient'
import { NOTIFICATION_FALLBACKS, NOTIFICATION_SEVERITIES, type NotificationSeverity } from '@/constants/notifications'

export type { NotificationSeverity } from '@/constants/notifications'

export interface AgentLog {
  agent_name: string
  event_type?: string
  message?: string
  timestamp: string
  confidence?: number
  latency_ms?: number
  primary_edge?: string
  stream?: unknown
  message_id?: unknown
  data?: unknown
  id?: string | number
  agent?: string
  action?: string
  symbol?: string
  [key: string]: unknown
}

export interface Order {
  symbol: string
  pnl: number
  side: 'long' | 'short'
  quantity: number
  entry_price: number
  current_price: number
  timestamp: string
  pnl_percent?: number
  order_id?: string | number
  [key: string]: unknown
}

export interface Position {
  symbol: string
  side: 'long' | 'short'
  quantity: number
  entry_price: number
  current_price: number
  pnl: number
  pnl_percent?: number
  [key: string]: unknown
}

export interface SystemMetric {
  metric_name: string
  value: number
  id?: string | number
  [key: string]: unknown
}

export interface LearningEvent {
  type: string
  timestamp: string
  id?: string | number
  [key: string]: unknown
}

export interface NotificationDisplayItem {
  label: string
  value: string
  tone?: string
}

export interface NotificationDisplayBadge {
  label: string
  tone?: string
}

export interface NotificationDisplay {
  kind?: string
  tone?: string
  icon?: string
  title?: string
  subtitle?: string
  status_label?: string
  badges?: NotificationDisplayBadge[]
  facts?: NotificationDisplayItem[]
  meta?: NotificationDisplayItem[]
}

export interface Notification {
  id: string
  severity: NotificationSeverity
  title?: string
  body?: string
  message: string
  notification_type: string
  stream_source?: string
  action?: string
  symbol?: string
  qty?: number | null
  fill_price?: number | null
  notional?: number | null
  pnl?: number | null
  pnl_percent?: number | null
  order_id?: string | number | null
  trace_id?: string
  state?: 'open' | 'resolved'
  delivery?: Record<string, unknown>
  display?: NotificationDisplay
  timestamp: string
}

export type ProposalStatus = 'pending' | 'approved' | 'rejected'
export type ProposalType = 'parameter_change' | 'code_change' | 'regime_adjustment' | 'new_agent' | 'challenger_result'

export interface Proposal {
  id: string
  proposal_type: ProposalType
  content: string
  requires_approval: boolean
  reflection_trace_id?: string
  confidence?: number
  timestamp: string
  status: ProposalStatus
  // Our branch fields (from events table / WS proposals stream)
  symbol?: string | null
  action?: string | null
  grade_score?: number | null
  bias?: string | null
  buys?: number | null
  sells?: number | null
  strategy_name?: string | null
  trace_id?: string | null
  created_at?: string | null
  source?: string | null
}

export interface PriceData {
  price: number
  change: number
  changePercent?: number
  previousPrice?: number
  updatedAt?: string
  [key: string]: unknown
}

export interface StreamStat {
  count: number
  lastMessageTimestamp: string | null
}

export interface AgentStatus {
  name: string
  status: string
  event_count: number
  last_event: string
  last_seen: number
  last_seen_at?: string
  source?: string
  seconds_ago: number
  last_grade_score?: number
}

export interface WsDiagnostics {
  reconnectAttempts: number
  messageRate: number
  lastError: string | null
}

export interface TradeFeedItem {
  id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number | null
  entry_price: number | null
  exit_price: number | null
  pnl: number | null
  pnl_percent: number | null
  order_id: string | null
  execution_trace_id: string | null
  signal_trace_id: string | null
  grade: string | null
  grade_score: number | null
  grade_label: string | null
  status: string
  filled_at: string | null
  graded_at: string | null
  reflected_at: string | null
  created_at: string | null
}

/** Normalize a raw trade dict (from REST or WS) into a well-typed TradeFeedItem. */
export function normalizeTradeFeedItem(raw: Record<string, unknown>): TradeFeedItem {
  const toNum = (v: unknown): number | null => (typeof v === 'number' && isFinite(v) ? v : null)
  const toStr = (v: unknown): string | null => (v != null ? String(v) : null)
  return {
    id: String(raw.id ?? Date.now()),
    symbol: String(raw.symbol ?? ''),
    side: raw.side === 'sell' ? 'sell' : 'buy',
    qty: toNum(raw.qty),
    entry_price: toNum(raw.entry_price),
    exit_price: toNum(raw.exit_price),
    pnl: toNum(raw.pnl),
    pnl_percent: toNum(raw.pnl_percent),
    order_id: toStr(raw.order_id),
    execution_trace_id: toStr(raw.execution_trace_id),
    signal_trace_id: toStr(raw.signal_trace_id),
    grade: toStr(raw.grade),
    grade_score: toNum(raw.grade_score),
    grade_label: toStr(raw.grade_label),
    status: String(raw.status ?? 'filled'),
    filled_at: toStr(raw.filled_at),
    graded_at: toStr(raw.graded_at),
    reflected_at: toStr(raw.reflected_at),
    created_at: String(raw.created_at ?? raw.timestamp ?? new Date().toISOString()),
  }
}

export interface AgentInstance {
  id: string
  instance_key: string
  pool_name: string
  status: 'active' | 'retired'
  started_at: string | null
  retired_at: string | null
  event_count: number
  uptime_seconds: number
}

export interface PerformanceSummary {
  total_pnl: number
  total_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  best_trade: number
  worst_trade: number
}

export interface DailyPnl {
  day: string
  pnl: number
  trade_count: number
  wins: number
  losses: number
  avg_pnl: number
}

export interface RecentEvent {
  stream: string
  msgId: string
  timestamp: string
}

type DashboardData = {
  system_metrics?: SystemMetric[]
  orders?: Order[]
  agent_logs?: AgentLog[]
  learning_events?: LearningEvent[]
  risk_alerts?: Array<Record<string, unknown>>
  signals?: Array<Record<string, unknown>>
  positions?: Position[]
  prices?: Record<string, PriceData>
  proposals?: Array<Record<string, unknown>>
  trade_feed?: TradeFeedItem[]
  notifications?: Array<Record<string, unknown>>
  ic_weights?: Record<string, number>
  agent_statuses?: Array<Record<string, unknown>>
  timestamp: string
  /** Runtime persistence mode — "db" | "in_memory_fallback". Present when backend is in memory mode. */
  mode?: string
  /** True when DB is unavailable and the system is operating from in-memory state. */
  degraded_mode?: boolean
  /** Machine-readable reason: "db_unavailable" | "redis_unavailable" */
  degraded_reason?: string
}

type PriceRecord = Record<string, PriceData>

function normalizeNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const cast = Number(value)
  return Number.isFinite(cast) ? cast : null
}

function buildDeterministicNotificationId(raw: Record<string, unknown>): string {
  const basis = [
    raw.notification_id,
    raw.id,
    raw.trace_id,
    raw.timestamp,
    raw.notification_type,
    raw.title,
    raw.message,
    raw.body,
    raw.symbol,
    raw.action,
  ]
    .map((v) => String(v ?? ""))
    .join("|")
  if (!basis) return "0-unknown"
  let hash = 5381
  for (let i = 0; i < basis.length; i += 1) {
    hash = ((hash << 5) + hash) ^ basis.charCodeAt(i)
  }
  return `${Math.abs(hash >>> 0)}-det`
}

export function normalizeStoredNotification(input: unknown): Notification | null {
  if (!input || typeof input !== 'object') return null
  const raw = input as Record<string, unknown>
  const severity = String(raw.severity || NOTIFICATION_FALLBACKS.severity).toLowerCase()
  const normalizedSeverity: NotificationSeverity = (
    NOTIFICATION_SEVERITIES as readonly string[]
  ).includes(severity)
    ? (severity as NotificationSeverity)
    : NOTIFICATION_FALLBACKS.severity

  const display =
    raw.display && typeof raw.display === 'object' && !Array.isArray(raw.display)
      ? (raw.display as NotificationDisplay)
      : undefined
  const message = String(raw.message || raw.body || display?.subtitle || '').trim()
  if (!message) return null

  // Prefer the backend's stable notification_id so the same fill survives a
  // page reload without being treated as a new notification.
  const stableId = raw.notification_id ?? raw.id ?? buildDeterministicNotificationId(raw)
  const notification: Notification = {
    id: String(stableId),
    severity: normalizedSeverity,
    title: raw.title ? String(raw.title) : (raw.body ? String(raw.body) : undefined),
    message,
    notification_type: String(raw.notification_type || NOTIFICATION_FALLBACKS.notificationType),
    stream_source: raw.stream_source ? String(raw.stream_source) : undefined,
    action: raw.action ? String(raw.action) : undefined,
    symbol: raw.symbol ? String(raw.symbol) : undefined,
    qty: normalizeNumber(raw.qty),
    fill_price: normalizeNumber(raw.fill_price),
    notional: normalizeNumber(raw.notional),
    pnl: normalizeNumber(raw.pnl),
    pnl_percent: normalizeNumber(raw.pnl_percent),
    order_id: raw.order_id == null ? null : String(raw.order_id),
    trace_id: raw.trace_id ? String(raw.trace_id) : undefined,
    state: String(raw.state || 'open').toLowerCase() === 'resolved' ? 'resolved' : 'open',
    delivery:
      raw.delivery && typeof raw.delivery === 'object' && !Array.isArray(raw.delivery)
        ? (raw.delivery as Record<string, unknown>)
        : undefined,
    display,
    timestamp: String(raw.timestamp || new Date().toISOString()),
  }

  return notification
}

// Type for price data from API
interface CachedPriceData {
  price: string | number;
  bid?: string;
  ask?: string;
  timestamp: string;
  source?: string;
}

type CodexState = {
  prices: PriceRecord
  orders: Order[]
  positions: Position[]
  signals: Array<Record<string, unknown>>
  agentLogs: AgentLog[]
  riskAlerts: Array<Record<string, unknown>>
  notifications: Notification[]
  proposals: Proposal[]
  tradeFeed: TradeFeedItem[]
  agentInstances: AgentInstance[]
  performanceSummary: PerformanceSummary | null
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
  agentStatuses: AgentStatus[]
  pipelineMetrics: Record<string, number>
  setAgentStatuses: (agents: AgentStatus[]) => void
  setPipelineMetrics: (metrics: Record<string, number>) => void
  setTradeFeed: (trades: TradeFeedItem[]) => void
  addTradeFeedItem: (trade: TradeFeedItem) => void
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
  addProposal: (proposal: Omit<Proposal, 'id' | 'status'>) => void
  updateProposalStatus: (id: string, status: ProposalStatus) => void
  addLearningEvent: (event: LearningEvent) => void
  addSystemMetric: (metric: SystemMetric) => void
  setDashboardData: (data: DashboardData | null) => void
  setLoading: (loading: boolean) => void
  setRegime: (regime: string) => void
  setKillSwitch: (active: boolean) => void
  setWsConnected: (connected: boolean) => void
  setWsDiagnostics: (diagnostics: Partial<WsDiagnostics>) => void
  trackWsMessage: (event: { stream?: string | null; msgId?: string | null; timestamp?: string | null }) => void
  trackMarketTick: (symbol?: string | null) => void
  hydrateDashboard: (data: DashboardData) => void
  hydrateFromLocalStorage: () => void
  bulkUpdate: (updates: Partial<CodexState>) => void
  fetchPrices: () => Promise<void>
}

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
export const useCodexStore = create<CodexState>((set) => ({
  prices: {},
  orders: [],
  positions: [],
  signals: [],
  agentLogs: [],
  riskAlerts: [],
  notifications: [],
  proposals: [],
  tradeFeed: [],
  agentInstances: [],
  performanceSummary: null,
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
  setAgentInstances: (agentInstances) => set({ agentInstances }),
  setPerformanceSummary: (performanceSummary) => set({ performanceSummary }),
  setDailyPnl: (dailyPnl) => set({ dailyPnl }),

  updatePrice: (symbol, price, change) => set((state) => ({
    prices: {
      ...state.prices,
      [symbol]: {
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

            updatedPrices[symbol] = {
              price,
              change,
              previousPrice,
              updatedAt: priceData.timestamp || new Date().toISOString(),
            }
          }
        }
        return { prices: updatedPrices }
      })
    } catch (error) {
      console.error('Error fetching prices:', error)
    }
  },
  addSignal: (signal) => set((state) => ({
    signals: [signal, ...state.signals].slice(0, 50)
  })),
  addOrder: (order) => set((state) => {
    const next = [order, ...state.orders].slice(0, 100)
    _saveToStorage('codex.orders', next)
    return { orders: next }
  }),
  updateOrder: (order) => set((state) => {
    const next = state.orders.some((e) => e.order_id === order.order_id)
      ? state.orders.map((e) => e.order_id === order.order_id ? { ...e, ...order } : e)
      : [order, ...state.orders].slice(0, 100)
    _saveToStorage('codex.orders', next)
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
    const next = [normalized, ...state.notifications].slice(0, 200)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('codex.notifications', JSON.stringify(next))
    }
    return { notifications: next }
  }),
  addProposal: (proposal) => set((state) => ({
    proposals: [
      { ...proposal, id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, status: 'pending' as ProposalStatus },
      ...state.proposals,
    ].slice(0, 50)
  })),
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
  trackWsMessage: ({ stream, msgId, timestamp }) =>
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
    const orders = _loadFromStorage<Order>('codex.orders', 100)
    const positions = _loadFromStorage<Position>('codex.positions', 50)
    let notifications: Notification[] = []
    try {
      const raw = window.localStorage.getItem('codex.notifications')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          notifications = parsed
            .map(normalizeStoredNotification)
            .filter((item): item is Notification => item !== null)
            .slice(0, 200)
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
      const updates: Partial<CodexState> = {
        dashboardData: data,
        isLoading: false
      }

      if (data.system_metrics) {
        updates.systemMetrics = [
          ...data.system_metrics,
          ...currentState.systemMetrics
        ].slice(0, 100)
      }

      if (data.orders) {
        updates.orders = [
          ...data.orders,
          ...currentState.orders.filter((order) =>
            !data.orders?.some((newOrder) => newOrder.order_id === order.order_id)
          )
        ].slice(0, 100)
        _saveToStorage('codex.orders', updates.orders)
      }

      if (data.agent_logs) {
        const incomingLogs = (data.agent_logs as unknown[]).flatMap((raw) => {
          if (!raw || typeof raw !== 'object') return []
          const r = raw as Record<string, unknown>
          const log: AgentLog = {
            agent_name: String(r.agent_name || r.agent || r.source_agent || 'Unknown'),
            event_type: String(r.event_type || r.action || r.type || 'processed'),
            timestamp: String(r.timestamp || r.created_at || new Date().toISOString()),
            symbol: r.symbol as string | undefined,
            action: r.action as string | undefined,
            latency_ms: Number(r.latency_ms) || 0,
            primary_edge: r.primary_edge as string | undefined,
          }
          if (r.id != null) log.id = r.id as string | number
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

      if (data.learning_events) {
        updates.learningEvents = [
          ...data.learning_events,
          ...currentState.learningEvents.filter((event) =>
            !data.learning_events?.some((newEvent) => newEvent.id === event.id)
          )
        ].slice(0, 50)
      }

      if (data.risk_alerts) {
        updates.riskAlerts = [
          ...data.risk_alerts,
          ...currentState.riskAlerts.filter((alert) =>
            !data.risk_alerts?.some((newAlert) => newAlert.id === alert.id)
          )
        ].slice(0, 50)
      }

      if (data.signals) {
        updates.signals = [
          ...data.signals,
          ...currentState.signals.filter((signal) =>
            !data.signals?.some((newSignal) => newSignal.id === signal.id)
          )
        ].slice(0, 50)
      }

      if (data.positions) {
        updates.positions = data.positions
        _saveToStorage('codex.positions', data.positions)
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
            content: String(p.content ?? ''),
            requires_approval: p.requires_approval !== false,
            confidence: typeof p.confidence === 'number' ? p.confidence : undefined,
            reflection_trace_id: p.reflection_trace_id as string | undefined,
            timestamp: (p.timestamp as string) ?? new Date().toISOString(),
            status: (p.status as ProposalStatus) ?? 'pending' as ProposalStatus,
          }))
        if (newProposals.length > 0) {
          updates.proposals = [...newProposals, ...currentState.proposals].slice(0, 50)
        }
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
            window.localStorage.setItem('codex.notifications', JSON.stringify(next))
          }
        }
      }

      if (data.agent_statuses && Array.isArray(data.agent_statuses)) {
        updates.agentStatuses = data.agent_statuses as unknown as AgentStatus[]
      }

      return updates
    })
  },

  bulkUpdate: (updates: Partial<CodexState>) => {
    set(updates)
  }
}))
