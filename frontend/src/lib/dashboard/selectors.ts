/**
 * Pure view-model selectors for the dashboard.
 *
 * These extract the data-shaping logic out of `DashboardView.tsx` so the
 * components stay declarative. Every function here is deterministic and
 * unit-testable in isolation.
 */

import type {
  AgentLog,
  AgentStatus as StoreAgentStatus,
  AgentInstance,
  Order,
  Position,
  SystemMetric,
  TradeFeedItem,
} from '@/stores/useCodexStore'
import { toFiniteNumber, parseTimestamp } from '@/lib/format'
import {
  type AgentStatus,
  pickHigherPriorityStatus,
  isClosedTrade,
  compareAgentStatus,
} from '@/lib/state'
import {
  AGENT_STALE_THRESHOLD_MS,
  canonicalAgentKey,
  getLiveThresholdMs,
} from '@/lib/constants/agentStates'
import type {
  AgentSummary,
  DashboardSummaryView,
  WiringFreshness,
} from '@/lib/types/dashboard'

/** Heartbeat may be in `last_seen_at` (ISO), `last_seen` (epoch), or legacy `last_event`. */
export function parseHeartbeatTimestamp(status: StoreAgentStatus): Date | null {
  return (
    parseTimestamp(status.last_seen_at) ??
    parseTimestamp(status.last_seen) ??
    parseTimestamp(status.last_event)
  )
}

/** Look up a system metric by name and coerce its value. */
export function getMetric(
  systemMetrics: Array<Record<string, unknown>>,
  metricName: string,
): number | null {
  const match = systemMetrics.find((metric) => metric?.metric_name === metricName)
  return toFiniteNumber(match?.value)
}

/**
 * Build the headline DAILY-summary tile values from the raw store payloads.
 */
export function buildDashboardSummary(
  orders: Order[],
  positions: Position[],
  systemMetrics: SystemMetric[],
  dashboardData: Record<string, unknown> | null | undefined,
): DashboardSummaryView {
  const dailyPnlNumeric = orders.reduce(
    (sum, order) => sum + (toFiniteNumber(order?.pnl) ?? 0),
    0,
  )
  const closedTrades = orders.filter(
    (order) => isClosedTrade(order) && toFiniteNumber(order?.pnl) != null,
  )
  const wins = closedTrades.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) > 0).length
  const winRate = closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : null

  const activePositions = positions.filter(
    (position) => position?.side === 'long' || position?.side === 'short',
  ).length

  const dailyChangeFromMetric = getMetric(systemMetrics, 'daily_change_pct')
  const dailyChangeFromDashboard = toFiniteNumber(
    (dashboardData ?? null)?.daily_change_pct,
  )
  const baseEquity =
    getMetric(systemMetrics, 'portfolio_value') ??
    getMetric(systemMetrics, 'account_equity') ??
    getMetric(systemMetrics, 'equity') ??
    getMetric(systemMetrics, 'starting_equity')
  const computedDailyChange =
    baseEquity && baseEquity > 0 ? (dailyPnlNumeric / baseEquity) * 100 : null
  const dailyChange = dailyChangeFromMetric ?? dailyChangeFromDashboard ?? computedDailyChange

  return {
    dailyPnlNumeric,
    winRate,
    activePositions,
    dailyChange,
    hasOrders: orders.length > 0,
    hasClosedTrades: closedTrades.length > 0,
  }
}

/** Locally derive performance summary from closed orders when API summary is empty. */
export function buildFallbackPerformanceSummary(orders: Order[]): {
  total_pnl: number
  win_rate: number
  best_trade: number
  worst_trade: number
} | null {
  const closedPnls = orders
    .filter((order) => isClosedTrade(order))
    .map((order) => toFiniteNumber(order?.pnl))
    .filter((pnl): pnl is number => pnl != null)
  if (closedPnls.length === 0) return null
  const total = closedPnls.reduce((sum, pnl) => sum + pnl, 0)
  const wins = closedPnls.filter((pnl) => pnl > 0)
  return {
    total_pnl: total,
    win_rate: wins.length / closedPnls.length,
    best_trade: Math.max(...closedPnls),
    worst_trade: Math.min(...closedPnls),
  }
}

/**
 * Combine real-time agent logs, heartbeat statuses, and persisted instances
 * into a single sorted list of AgentSummary rows for the dashboard.
 */
export function buildAgentSummaries(
  agentLogs: AgentLog[],
  agentStatuses: StoreAgentStatus[],
  agentInstances: AgentInstance[],
  now: number = Date.now(),
): AgentSummary[] {
  const grouped = agentLogs.reduce<
    Record<string, { displayName: string; count: number; lastSeen: Date | null }>
  >((acc, log) => {
    const rawName = String(log?.agent_name ?? log?.agent ?? '').trim()
    if (!rawName) return acc
    const agentKey = canonicalAgentKey(rawName)
    const safeDate = parseTimestamp(log?.timestamp ?? log?.created_at)
    const existing = acc[agentKey] ?? { displayName: rawName, count: 0, lastSeen: null }
    const newest =
      !existing.lastSeen || (safeDate && safeDate > existing.lastSeen)
        ? safeDate
        : existing.lastSeen
    acc[agentKey] = {
      displayName: existing.displayName,
      count: existing.count + 1,
      lastSeen: newest,
    }
    return acc
  }, {})

  const incomingAgents = Object.entries(grouped).map<AgentSummary>(
    ([agentKey, data]) => {
      const ageMs = data.lastSeen ? now - data.lastSeen.getTime() : Infinity
      const liveThreshold = getLiveThresholdMs(agentKey)
      const status: AgentStatus =
        ageMs <= liveThreshold ? 'Live' : ageMs <= AGENT_STALE_THRESHOLD_MS ? 'Stale' : 'Idle'
      const tier: AgentSummary['tier'] =
        status === 'Live' ? 'active' : data.count > 0 ? 'challenger' : 'inactive'
      return {
        name: data.displayName,
        realtimeCount: data.count,
        persistedCount: 0,
        lastSeen: data.lastSeen,
        status,
        tier,
        source: 'realtime',
      }
    },
  )

  const normalizedByName = new Map(
    incomingAgents.map((agent) => [canonicalAgentKey(agent.name), agent]),
  )

  for (const status of agentStatuses) {
    const agentKey = canonicalAgentKey(status.name)
    const existing = normalizedByName.get(agentKey)
    const statusDate = parseHeartbeatTimestamp(status)
    const ageMs = statusDate ? now - statusDate.getTime() : Number.POSITIVE_INFINITY
    const eventCount = status.event_count ?? 0
    const mappedStatus: AgentStatus =
      ageMs <= getLiveThresholdMs(agentKey)
        ? 'Live'
        : eventCount === 0
          ? 'Idle'
          : 'Stale'
    const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
    const lastSeen = pickNewerDate(existing?.lastSeen, statusDate)
    normalizedByName.set(agentKey, {
      name: existing?.name ?? status.name,
      realtimeCount: Math.max(existing?.realtimeCount ?? 0, eventCount),
      persistedCount: existing?.persistedCount ?? 0,
      lastSeen,
      status: mergedStatus,
      tier:
        mergedStatus === 'Live'
          ? 'active'
          : mergedStatus === 'Error'
            ? 'inactive'
            : 'challenger',
      source: existing ? 'hybrid' : 'realtime',
    })
  }

  for (const inst of agentInstances) {
    const agentKey = canonicalAgentKey(inst.pool_name)
    const existing = normalizedByName.get(agentKey)
    const startedDate = parseTimestamp(inst.started_at)
    const mappedStatus: AgentStatus = inst.status === 'active' ? 'Stale' : 'Idle'
    const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
    const lastSeen = pickNewerDate(existing?.lastSeen, startedDate)
    normalizedByName.set(agentKey, {
      name: existing?.name ?? inst.pool_name,
      realtimeCount: existing?.realtimeCount ?? 0,
      persistedCount: Math.max(existing?.persistedCount ?? 0, inst.event_count ?? 0),
      lastSeen,
      status: mergedStatus,
      tier:
        mergedStatus === 'Live'
          ? 'active'
          : mergedStatus === 'Error'
            ? 'inactive'
            : 'challenger',
      source: existing ? 'hybrid' : 'persisted',
    })
  }

  return Array.from(normalizedByName.values()).sort((a, b) => {
    const byStatus = compareAgentStatus(a.status, b.status)
    if (byStatus !== 0) return byStatus
    return a.name.localeCompare(b.name)
  })
}

function pickNewerDate(a: Date | null | undefined, b: Date | null | undefined): Date | null {
  return [a, b]
    .filter((d): d is Date => d instanceof Date)
    .sort((x, y) => y.getTime() - x.getTime())[0] ?? null
}

/** Trade feed P&L aggregates. */
export function buildTradeFeedAggregates(tradeFeed: TradeFeedItem[]): {
  realizedPnl: number
  totalTrades: number
  wins: number
  pnlWinRate: number
} {
  const realizedPnl = tradeFeed.reduce((sum, row) => sum + (row.pnl ?? 0), 0)
  const totalTrades = tradeFeed.filter((row) => row.pnl != null).length
  const wins = tradeFeed.filter((row) => (row.pnl ?? 0) > 0).length
  const pnlWinRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
  return { realizedPnl, totalTrades, wins, pnlWinRate }
}

/** Newest-row age across heartbeat / instance / log surfaces. */
export function buildWiringFreshness(
  agentStatuses: StoreAgentStatus[],
  agentInstances: AgentInstance[],
  agentLogs: AgentLog[],
  now: number = Date.now(),
): WiringFreshness {
  const latestHeartbeat = agentStatuses
    .map((row) => parseHeartbeatTimestamp(row)?.getTime() ?? Number.NaN)
    .filter((ts) => Number.isFinite(ts))
    .sort((a, b) => b - a)[0]
  const latestInstance = agentInstances
    .map((row) => parseTimestamp(row.started_at)?.getTime() ?? Number.NaN)
    .filter((ts) => Number.isFinite(ts))
    .sort((a, b) => b - a)[0]
  const latestLog = agentLogs
    .map((row) => parseTimestamp(row.timestamp ?? row.created_at)?.getTime() ?? Number.NaN)
    .filter((ts) => Number.isFinite(ts))
    .sort((a, b) => b - a)[0]
  return {
    heartbeatAgeMs: latestHeartbeat ? now - latestHeartbeat : null,
    instanceAgeMs: latestInstance ? now - latestInstance : null,
    logAgeMs: latestLog ? now - latestLog : null,
  }
}
