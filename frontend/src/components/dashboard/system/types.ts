import type { AgentLog, AgentStatus, Notification, Order, Position, Proposal, TradeFeedItem } from '@/stores/useCodexStore'

export interface RecentEventLike {
  stream?: string | null
  msgId?: string | null
  timestamp?: string | null
}

export interface StreamStat {
  count: number
  lastMessageTimestamp: string | null
}

export interface PersistedHistoryItem {
  id: string
  kind: string
  source?: string | null
  trace_id?: string | null
  created_at: string | null
}

export interface PersistedStreamCount {
  stream: string
  processed_count: number
  last_processed_at: string | null
}

export interface ApiHealth {
  dashboardState: 'pending' | 'ok' | 'error'
  agentInstances: 'pending' | 'ok' | 'error'
  eventHistory: 'pending' | 'ok' | 'error'
}

export interface PerformanceSummaryLike {
  total_pnl?: number | null
  win_rate?: number | null
  best_trade?: number | null
  worst_trade?: number | null
}

export interface WsDiagnosticsLike {
  reconnectAttempts: number
  messageRate: number
  lastError: string | null
}

export type StatusTone = 'ok' | 'warn' | 'err' | 'neutral'
export type AlertVariant = 'ok' | 'warn' | 'err' | 'info'

export type PipelineStatus = 'Healthy' | 'Degraded' | 'Stalled'

export interface SystemDashboardProps {
  wsConnected: boolean
  wsMessageCount: number
  wsLastMessageTimestamp: string | null
  wsDiagnostics: WsDiagnosticsLike
  streamStats: Record<string, StreamStat>
  recentEvents: RecentEventLike[]
  agentStatuses: AgentStatus[]
  prices: Record<string, unknown>
  positions: Position[]
  tradeFeed: TradeFeedItem[]
  orders: Order[]
  agentLogs: AgentLog[]
  notifications: Notification[]
  proposals: Proposal[]
  riskAlerts: Array<Record<string, unknown>>
  pricesFetched: boolean
  isInMemoryMode: boolean
  resolvedPerformanceSummary: PerformanceSummaryLike | null
  apiHealth: ApiHealth
  systemFeedError: string | null
  llmAvailable: boolean | null
  llmProvider: string
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]
  regime: string
  killSwitchActive: boolean
  setActiveTraceId: (id: string | null) => void
}
