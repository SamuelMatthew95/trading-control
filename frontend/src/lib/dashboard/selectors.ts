import { type AgentStatus } from '@/stores/useCodexStore'
import { parseTimestamp, toFiniteNumber } from '@/lib/formatters'

export type AgentSummary = {
  name: string
  realtimeCount: number
  persistedCount: number
  lastSeen: Date | null
  status: 'Live' | 'Stale' | 'Error' | 'Idle'
  tier: 'active' | 'challenger' | 'inactive'
  source: 'realtime' | 'persisted' | 'hybrid'
}

export function parseHeartbeatTimestamp(status: AgentStatus): Date | null {
  return parseTimestamp(status.last_seen_at) ?? parseTimestamp(status.last_seen) ?? parseTimestamp(status.last_event)
}

export function buildDashboardSummary(params: {
  orders: Array<Record<string, unknown>>
  positions: Array<Record<string, unknown>>
  dailyChangeFromMetric: number | null
  dailyChangeFromDashboard: number | null
  baseEquity: number | null
  isClosedTrade: (o: Record<string, unknown>) => boolean
}) {
  const { orders, positions, dailyChangeFromMetric, dailyChangeFromDashboard, baseEquity, isClosedTrade } = params
  const dailyPnlNumeric = orders.reduce((sum, order) => sum + (toFiniteNumber(order?.pnl) ?? 0), 0)
  const closedTrades = orders.filter((order) => isClosedTrade(order) && toFiniteNumber(order?.pnl) != null)
  const wins = closedTrades.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) > 0).length
  const winRate = closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : null
  const activePositions = positions.filter((position) => position?.side === 'long' || position?.side === 'short').length
  const computedDailyChange = baseEquity && baseEquity > 0 ? (dailyPnlNumeric / baseEquity) * 100 : null
  return {
    dailyPnlNumeric,
    winRate,
    activePositions,
    dailyChange: dailyChangeFromMetric ?? dailyChangeFromDashboard ?? computedDailyChange,
    hasOrders: orders.length > 0,
    hasClosedTrades: closedTrades.length > 0,
  }
}

export function buildFallbackPerformanceSummary(orders: Array<Record<string, unknown>>, isClosedTrade: (o: Record<string, unknown>) => boolean) {
  const closedPnls = orders.filter(isClosedTrade).map((order) => toFiniteNumber(order?.pnl)).filter((p): p is number => p != null)
  if (closedPnls.length === 0) return null
  const total = closedPnls.reduce((sum, pnl) => sum + pnl, 0)
  const wins = closedPnls.filter((pnl) => pnl > 0)
  return { total_pnl: total, win_rate: wins.length / closedPnls.length, best_trade: Math.max(...closedPnls), worst_trade: Math.min(...closedPnls) }
}
