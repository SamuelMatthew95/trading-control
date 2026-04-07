'use client'
import { create } from 'zustand'
import { api } from '@/lib/apiClient'

export interface AgentLog {
  agent_name: string
  message?: string
  timestamp: string
  confidence?: number
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

export type NotificationSeverity = 'CRITICAL' | 'URGENT' | 'WARNING' | 'INFO'

export interface Notification {
  id: string
  severity: NotificationSeverity
  message: string
  notification_type: string
  stream_source?: string
  timestamp: string
  acknowledged: boolean
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
  seconds_ago: number
  last_grade_score?: number
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
  ic_weights?: Record<string, number>
  agent_statuses?: Array<Record<string, unknown>>
  timestamp: string
}

type PriceRecord = Record<string, PriceData>

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
  addNotification: (notification: Omit<Notification, 'id' | 'acknowledged'>) => void
  acknowledgeNotification: (id: string) => void
  addProposal: (proposal: Omit<Proposal, 'id' | 'status'>) => void
  updateProposalStatus: (id: string, status: ProposalStatus) => void
  addLearningEvent: (event: LearningEvent) => void
  addSystemMetric: (metric: SystemMetric) => void
  setDashboardData: (data: DashboardData | null) => void
  setLoading: (loading: boolean) => void
  setRegime: (regime: string) => void
  setKillSwitch: (active: boolean) => void
  setWsConnected: (connected: boolean) => void
  trackWsMessage: (event: { stream?: string | null; msgId?: string | null; timestamp?: string | null }) => void
  trackMarketTick: (symbol?: string | null) => void
  hydrateDashboard: (data: DashboardData) => void
  bulkUpdate: (updates: Partial<CodexState>) => void
  fetchPrices: () => Promise<void>
}

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
  setTradeFeed: (tradeFeed) => set({ tradeFeed }),
  addTradeFeedItem: (trade) => set((state) => ({
    tradeFeed: [trade, ...state.tradeFeed].slice(0, 200),
  })),
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
  addOrder: (order) => set((state) => ({
    orders: [order, ...state.orders].slice(0, 100)
  })),
  updateOrder: (order) => set((state) => ({
    orders: state.orders.some((e) => e.order_id === order.order_id)
      ? state.orders.map((e) => e.order_id === order.order_id ? { ...e, ...order } : e)
      : [order, ...state.orders].slice(0, 100)
  })),
  addAgentLog: (log) => set((state) => ({
    agentLogs: [log, ...state.agentLogs].slice(0, 100)
  })),
  addRiskAlert: (alert) => set((state) => ({
    riskAlerts: [alert, ...state.riskAlerts].slice(0, 50)
  })),
  addNotification: (notification) => set((state) => ({
    notifications: [
      { ...notification, id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, acknowledged: false },
      ...state.notifications,
    ].slice(0, 100)
  })),
  acknowledgeNotification: (id) => set((state) => ({
    notifications: state.notifications.map((n) => n.id === id ? { ...n, acknowledged: true } : n)
  })),
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
    systemMetrics: [metric, ...state.systemMetrics].slice(0, 100)
  })),
  setDashboardData: (data) => set({ dashboardData: data }),
  setLoading: (isLoading) => set({ isLoading }),
  setRegime: (regime) => set({ regime }),
  setKillSwitch: (killSwitchActive) => set({ killSwitchActive }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  trackWsMessage: ({ stream, msgId, timestamp }) =>
    set((state) => {
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
      }

      if (data.agent_logs) {
        updates.agentLogs = [
          ...data.agent_logs,
          ...currentState.agentLogs.filter((log) =>
            !data.agent_logs?.some((newLog) => newLog.id === log.id)
          )
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
          updates.proposals = [...newProposals, ...currentState.proposals].slice(0, 100)
        }
      }

      if (data.trade_feed && Array.isArray(data.trade_feed)) {
        const existingTfIds = new Set(currentState.tradeFeed.map((t) => t.id))
        const newTrades = data.trade_feed.filter((t) => !existingTfIds.has(t.id))
        if (newTrades.length > 0) {
          updates.tradeFeed = [...newTrades, ...currentState.tradeFeed].slice(0, 200)
        }
      }

      if (data.agent_statuses && Array.isArray(data.agent_statuses)) {
        updates.agentStatuses = data.agent_statuses as AgentStatus[]
      }

      return updates
    })
  },

  bulkUpdate: (updates: Partial<CodexState>) => {
    set(updates)
  }
}))
