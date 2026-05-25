'use client'

import { useCallback, useEffect, useMemo, useState, type ComponentType } from 'react'
// useEffect kept: used for showNoAgentDataMessage timer
import { useCodexStore, type AgentStatus } from '@/stores/useCodexStore'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { useRestPoll } from '@/hooks/useRestPoll'
import { cn } from '@/lib/utils'
import { formatUSD, signedUSD, formatTimeAgo, toFiniteNum as toFiniteNumber } from '@/lib/formatters'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { LearningDashboard } from '@/components/dashboard/LearningDashboard'
import { LLMHealthPanel } from '@/components/dashboard/LLMHealthPanel'
import { NotificationFeed } from '@/components/dashboard/NotificationFeed'
import { TradingView } from '@/components/dashboard/TradingView'
import { TraceModal } from '@/components/dashboard/TraceModal'
import { ProposalsSection } from '@/components/dashboard/ProposalsSection'
import { RecentDecisionsPanel } from '@/components/dashboard/RecentDecisionsPanel'
import { cardClass, sectionTitleClass, mutedClass, valueClass } from '@/lib/dashboard-styles'
import {
  Brain,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'

const sanitizeValue = (value: string | number | boolean | null | undefined): string => {
  if (value === undefined || value === null || value === '') return '--';
  if (typeof value === 'number' && (isNaN(value) || !isFinite(value))) return '--';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  return String(value);
};

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}

const formatAgeFromMs = (ageMs: number | null): string => {
  if (ageMs == null || ageMs < 0 || !Number.isFinite(ageMs)) return '--'
  const sec = Math.floor(ageMs / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  return `${hr}h`
}

const formatWiringAge = (ageMs: number | null): string => {
  const age = formatAgeFromMs(ageMs)
  return age === '--' ? 'No recent timestamp' : `last ${age} ago`
}


type Section = 'overview' | 'trading' | 'agents' | 'learning' | 'proposals' | 'system'

type AgentSummary = {
  name: string
  realtimeCount: number
  persistedCount: number
  lastSeen: Date | null
  status: 'Live' | 'Stale' | 'Error' | 'Idle'
  tier: 'active' | 'challenger' | 'inactive'
  source: 'realtime' | 'persisted' | 'hybrid'
}


function displayAgentName(rawName: string): string {
  const canonical = canonicalAgentKey(rawName)
  if (canonical === 'IC_UPDATER') return 'Indicator Cache Updater'
  return rawName
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

const TICKER_SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AAPL', 'TSLA', 'SPY'] as const
const AGENT_LIVE_THRESHOLD_MS = 10_000
const AGENT_STALE_THRESHOLD_MS = 120_000
// Per-agent overrides: Reasoning Agent can take 60-90s per LLM call.
const AGENT_LIVE_THRESHOLD_OVERRIDES: Record<string, number> = {
  REASONING_AGENT: 90_000,
}
const getLiveThresholdMs = (agentKey: string): number =>
  AGENT_LIVE_THRESHOLD_OVERRIDES[agentKey] ?? AGENT_LIVE_THRESHOLD_MS

function isClosedTrade(order: Record<string, unknown> | null | undefined): boolean {
  if (!order) return false
  const status = String(order.status ?? '').toLowerCase()
  if (status === 'filled' || status === 'closed' || status === 'executed' || status === 'completed') return true
  if (order.filled_at != null) return true
  return false
}

function parseTimestamp(value: unknown): Date | null {
  if (value == null) return null
  if (value instanceof Date) {
    const t = value.getTime()
    return Number.isNaN(t) || t <= 0 ? null : value
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null
    const ms = value > 10_000_000_000 ? value : value * 1000
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const raw = String(value).trim()
  if (!raw || raw === '0') return null
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const num = Number(raw)
    if (Number.isFinite(num) && num > 0) {
      const ms = num > 10_000_000_000 ? num : num * 1000
      const d = new Date(ms)
      if (!Number.isNaN(d.getTime())) return d
    }
    return null
  }
  const d = new Date(raw)
  if (Number.isNaN(d.getTime()) || d.getTime() <= 0) return null
  return d
}

function parseHeartbeatTimestamp(status: AgentStatus): Date | null {
  const fromIsoField = parseTimestamp(status.last_seen_at)
  if (fromIsoField) return fromIsoField
  const fromEpochField = parseTimestamp(status.last_seen)
  if (fromEpochField) return fromEpochField
  // Backward compatibility for older payloads that (incorrectly) used last_event as a timestamp.
  return parseTimestamp(status.last_event)
}

function canonicalAgentKey(name: string): string {
  return name.trim().toUpperCase().replace(/[\s-]+/g, '_')
}

function formatAgentSource(source: AgentSummary['source']): string {
  if (source === 'realtime') return 'Realtime'
  if (source === 'persisted') return 'Persisted'
  return 'Hybrid'
}

function pickHigherPriorityStatus(
  current: AgentSummary['status'] | undefined,
  incoming: AgentSummary['status'],
): AgentSummary['status'] {
  if (!current) return incoming
  const priority: Record<AgentSummary['status'], number> = {
    Live: 0,
    Stale: 1,
    Error: 2,
    Idle: 3,
  }
  return priority[incoming] < priority[current] ? incoming : current
}

function getMetric(systemMetrics: Array<Record<string, unknown>>, metricName: string): number | null {
  const match = systemMetrics.find((metric) => metric?.metric_name === metricName)
  return toFiniteNumber(match?.value)
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${remainingMinutes}m`
}

function EmptyState({ message, icon: Icon }: { message: string; icon?: ComponentType<{ className?: string }> }) {
  return (
    <div className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-10 dark:border-slate-800 dark:bg-slate-900/30">
      {Icon && <Icon className="h-5 w-5 text-slate-300 dark:text-slate-600" />}
      <p className="text-xs font-sans font-medium text-slate-400 dark:text-slate-600">{message}</p>
    </div>
  )
}

function PriceCardSkeleton() {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="mb-1 h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-1 h-6 w-24 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-2 flex items-center justify-between">
        <div className="h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="h-3 w-12 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      </div>
    </div>
  )
}




export function DashboardView({ section }: { section: Section }) {
  const {
    agentLogs = [],
    orders = [],
    prices = {},
    positions = [],
    systemMetrics = [],
    notifications = [],
    tradeFeed = [],
    agentInstances = [],
    performanceSummary,
    dashboardData,
    wsConnected,
    marketTickCount,
    lastMarketSymbol,
    streamStats,
    wsMessageCount,
    wsLastMessageTimestamp,
    wsDiagnostics,
    recentEvents = [],
    agentStatuses = [],
  } = useCodexStore()

  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)
  const [showNoAgentDataMessage, setShowNoAgentDataMessage] = useState(false)

  const {
    apiHealth,
    systemFeedError,
    llmAvailable,
    llmProvider,
    pricesFetched,
    tradeFeedEmptyReason,
    tradeFeedUpstream,
    decisionStats,
    recentDecisions,
    persistedCounts,
    persistedEvents,
    persistedLogs,
  } = useRestPoll(wsConnected)

  // Show skeletons only on the very first render before we've attempted a fetch.
  // Once we've tried (success or failure) show real cards so the UI doesn't
  // get stuck in skeleton mode when the price poller hasn't run yet.
  const pricesLoading = !pricesFetched && Object.keys(prices).length === 0
  const latestTickTs = streamStats['market_ticks']?.lastMessageTimestamp ?? null
  const dataLatencyMs = latestTickTs ? Math.max(Date.now() - new Date(latestTickTs).getTime(), 0) : null
  const wsLatencyMs = wsLastMessageTimestamp ? Math.max(Date.now() - new Date(wsLastMessageTimestamp).getTime(), 0) : null
  const recentEventLatencyMs = recentEvents.length > 0 && recentEvents[0]?.timestamp
    ? Math.max(Date.now() - new Date(recentEvents[0].timestamp).getTime(), 0)
    : null
  const effectiveLatencyMs = dataLatencyMs ?? wsLatencyMs ?? recentEventLatencyMs
  const throughput = Number(wsDiagnostics?.messageRate ?? 0)
  const pipelineStatus = !latestTickTs
    ? 'Stalled'
    : dataLatencyMs != null && dataLatencyMs < 15_000
      ? 'Healthy'
      : 'Degraded'
  const signalsCount = streamStats['signals']?.count ?? 0
  const ordersCount = streamStats['orders']?.count ?? 0
  const executionsCount = streamStats['executions']?.count ?? 0
  const pipelineWarning = signalsCount > 0 && ordersCount === 0
  const hasMarketData = Boolean(
    latestTickTs
    || (streamStats['market_ticks']?.count ?? 0) > 0
    || recentEvents.some((event) => event.stream === 'market_ticks' || event.stream === 'market_events'),
  )
  const isInMemoryMode = String((dashboardData as Record<string, unknown> | null)?.mode ?? '').includes('in_memory')
  const persistenceEnabled = Boolean(
    isInMemoryMode || persistedCounts.length > 0 || persistedEvents.length > 0 || persistedLogs.length > 0 || apiHealth.eventHistory === 'ok',
  )
  const signalAgentRealtimeCount = agentStatuses.find((agent) => canonicalAgentKey(agent.name) === 'SIGNAL_AGENT')?.event_count ?? 0
  const reasoningAgentStatus = agentStatuses.find((agent) => canonicalAgentKey(agent.name) === 'REASONING_AGENT')?.status ?? 'unknown'
  const executionAgentStatus = agentStatuses.find((agent) => canonicalAgentKey(agent.name) === 'EXECUTION_ENGINE')?.status ?? 'unknown'
  const realizedPnl = tradeFeed.reduce((sum, row) => sum + (row.pnl ?? 0), 0)
  const unrealizedPnl = positions.reduce((sum, row) => sum + (toFiniteNumber((row as Record<string, unknown>).pnl) ?? 0), 0)
  const totalTrades = tradeFeed.filter((row) => row.pnl != null).length
  const wins = tradeFeed.filter((row) => (row.pnl ?? 0) > 0).length
  const pnlWinRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
  const baseSystemStatus = useSystemStatus()
  const systemStatus = systemFeedError ? 'error' : baseSystemStatus

  const formatTimeAgoSafe = useCallback((date: Date) => formatTimeAgo(date), [])
  const summary = useMemo(() => {
    const dailyPnlNumeric = orders.reduce((sum, order) => sum + (toFiniteNumber(order?.pnl) ?? 0), 0)
    const closedTrades = orders.filter((order) => isClosedTrade(order) && toFiniteNumber(order?.pnl) != null)
    const wins = closedTrades.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) > 0).length
    const winRate = closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : null
    const activePositions = positions.filter((position) => position?.side === 'long' || position?.side === 'short').length
    const dailyChangeFromMetric = getMetric(systemMetrics, 'daily_change_pct')
    const dailyChangeFromDashboard = toFiniteNumber((dashboardData as Record<string, unknown> | null)?.['daily_change_pct'])
    const baseEquity = getMetric(systemMetrics, 'portfolio_value')
      ?? getMetric(systemMetrics, 'account_equity')
      ?? getMetric(systemMetrics, 'equity')
      ?? getMetric(systemMetrics, 'starting_equity')
    const computedDailyChange = baseEquity && baseEquity > 0 ? (dailyPnlNumeric / baseEquity) * 100 : null
    const dailyChange = dailyChangeFromMetric ?? dailyChangeFromDashboard ?? computedDailyChange

    return {
      dailyPnlNumeric,
      winRate,
      activePositions,
      dailyChange,
      hasOrders: orders.length > 0,
      hasClosedTrades: closedTrades.length > 0,
    }
  }, [orders, positions, systemMetrics, dashboardData])

  const fallbackPerformanceSummary = useMemo(() => {
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
  }, [orders])

  // The API summary is preferred ONLY if it actually carries data. In in-memory
  // mode the backend returns `{total_pnl: 0, win_rate: 0, ...}` even when the
  // session has real fills, which left Total/Best/Worst pinned to $0.00 while
  // the headline Daily P&L showed a real loss. Fall back to the locally
  // computed summary whenever the API response is uniformly zero AND we have
  // closed trades on the client.
  const apiSummaryHasSignal = performanceSummary != null && (
    (performanceSummary.total_pnl ?? 0) !== 0
    || (performanceSummary.win_rate ?? 0) !== 0
    || (performanceSummary.best_trade ?? 0) !== 0
    || (performanceSummary.worst_trade ?? 0) !== 0
  )
  const resolvedPerformanceSummary = apiSummaryHasSignal
    ? performanceSummary
    : (fallbackPerformanceSummary ?? performanceSummary)

  const realAgents = useMemo(() => {
    const grouped = agentLogs.reduce<Record<string, { displayName: string; count: number; lastSeen: Date | null }>>((acc, log) => {
      const name = sanitizeValue(log?.agent_name || log?.agent)
      if (name === '--') return acc
      const agentKey = canonicalAgentKey(name)
      const safeDate = parseTimestamp(log?.timestamp || log?.created_at)
      const existing = acc[agentKey] ?? { displayName: name, count: 0, lastSeen: null }
      const newest = !existing.lastSeen || (safeDate && safeDate > existing.lastSeen) ? safeDate : existing.lastSeen
      acc[agentKey] = { displayName: existing.displayName, count: existing.count + 1, lastSeen: newest }
      return acc
    }, {})

    const now = Date.now()
    const incomingAgents = Object.entries(grouped).map<AgentSummary>(([agentKey, data]) => {
      const ageMs = data.lastSeen ? now - data.lastSeen.getTime() : Infinity
      const liveThreshold = getLiveThresholdMs(agentKey)
      const status: AgentSummary['status'] = ageMs <= liveThreshold ? 'Live' : ageMs <= AGENT_STALE_THRESHOLD_MS ? 'Stale' : 'Idle'
      const tier: AgentSummary['tier'] = status === 'Live' ? 'active' : data.count > 0 ? 'challenger' : 'inactive'
      return {
        name: data.displayName,
        realtimeCount: data.count,
        persistedCount: 0,
        lastSeen: data.lastSeen,
        status,
        tier,
        source: 'realtime',
      }
    })

    const normalizedByName = new Map(incomingAgents.map((agent) => [canonicalAgentKey(agent.name), agent]))
    for (const status of agentStatuses) {
      const agentKey = canonicalAgentKey(status.name)
      const existing = normalizedByName.get(agentKey)
      const statusDate = parseHeartbeatTimestamp(status)
      const ageMs = statusDate ? now - statusDate.getTime() : Number.POSITIVE_INFINITY
      const eventCount = status.event_count ?? 0
      const mappedStatus: AgentSummary['status'] = ageMs <= getLiveThresholdMs(agentKey) ? 'Live' : eventCount === 0 ? 'Idle' : 'Stale'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, statusDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? status.name,
        realtimeCount: Math.max(existing?.realtimeCount ?? 0, status.event_count ?? 0),
        persistedCount: existing?.persistedCount ?? 0,
        lastSeen,
        status: mergedStatus,
        tier: mergedStatus === 'Live' ? 'active' : mergedStatus === 'Error' ? 'inactive' : 'challenger',
        source: existing ? 'hybrid' : 'realtime',
      })
    }

    for (const inst of agentInstances) {
      const agentKey = canonicalAgentKey(inst.pool_name)
      const existing = normalizedByName.get(agentKey)
      const startedDate = parseTimestamp(inst.started_at)
      const mappedStatus: AgentSummary['status'] = inst.status === 'active' ? 'Stale' : 'Idle'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, startedDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? inst.pool_name,
        realtimeCount: existing?.realtimeCount ?? 0,
        persistedCount: Math.max(existing?.persistedCount ?? 0, inst.event_count ?? 0),
        lastSeen,
        status: mergedStatus,
        tier: mergedStatus === 'Live' ? 'active' : mergedStatus === 'Error' ? 'inactive' : 'challenger',
        source: existing ? 'hybrid' : 'persisted',
      })
    }

    const priority: Record<AgentSummary['status'], number> = {
      Live: 0,
      Stale: 1,
      Error: 2,
      Idle: 3,
    }

    return Array.from(normalizedByName.values()).sort((a, b) => {
      const byStatus = priority[a.status] - priority[b.status]
      if (byStatus !== 0) return byStatus
      return a.name.localeCompare(b.name)
    })
  }, [agentLogs, agentStatuses, agentInstances])

  useEffect(() => {
    if (!wsConnected || realAgents.length > 0) {
      setShowNoAgentDataMessage(false)
      return
    }
    const timer = setTimeout(() => {
      const state = useCodexStore.getState()
      const hasAgentData = state.agentLogs.length > 0 || state.agentStatuses.length > 0 || state.agentInstances.length > 0
      if (!hasAgentData && state.wsConnected) {
        setShowNoAgentDataMessage(true)
      }
    }, 10000)
    return () => clearTimeout(timer)
  }, [realAgents.length, wsConnected])

  const wiringFreshness = useMemo(() => {
    const now = Date.now()
    const latestHeartbeat = agentStatuses
      .map((row) => parseHeartbeatTimestamp(row)?.getTime() ?? Number.NaN)
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]
    const latestInstance = agentInstances
      .map((row) => new Date(String(row.started_at || '')).getTime())
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]
    const latestLog = agentLogs
      .map((row) => new Date(String(row.timestamp || row.created_at || '')).getTime())
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]

    return {
      heartbeatAgeMs: latestHeartbeat ? now - latestHeartbeat : null,
      instanceAgeMs: latestInstance ? now - latestInstance : null,
      logAgeMs: latestLog ? now - latestLog : null,
    }
  }, [agentStatuses, agentInstances, agentLogs])

  const tickerEntries = useMemo(
    () => TICKER_SYMBOLS.map((symbol) => [symbol, prices[symbol]] as const),
    [prices]
  )

  const contentBySection = (
    <>
      {section === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { title: 'Daily P&L', value: summary.hasOrders ? signedUSD(summary.dailyPnlNumeric) : '--', trend: summary.hasOrders ? (summary.dailyPnlNumeric > 0 ? 1 : summary.dailyPnlNumeric < 0 ? -1 : 0) : 0 },
              { title: 'Win Rate', value: summary.winRate == null || !Number.isFinite(summary.winRate) ? '--' : `${summary.winRate.toFixed(2)}%${summary.hasClosedTrades ? '' : ' (open only)'}`, trend: 0 },
              { title: 'Active Positions', value: sanitizeValue(summary.activePositions), trend: 0 },
              { title: 'Daily Change %', value: `${typeof summary.dailyChange === 'number' && Number.isFinite(summary.dailyChange) ? summary.dailyChange.toFixed(2) : '0.00'}%`, trend: (summary.dailyChange ?? 0) > 0 ? 1 : (summary.dailyChange ?? 0) < 0 ? -1 : 0 },
            ].map((item) => (
              <div key={item.title} className={cardClass}>
                <div className="mb-3 flex items-center justify-between">
                  <p className={sectionTitleClass}>{item.title}</p>
                  {item.trend > 0 ? <TrendingUp className="h-4 w-4 text-emerald-500" /> : item.trend < 0 ? <TrendingDown className="h-4 w-4 text-rose-500" /> : <span className="h-4 w-4" />}
                </div>
                <p className={valueClass}>{item.value}</p>
              </div>
            ))}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Performance</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                {
                  label: 'Total P&L',
                  value: resolvedPerformanceSummary != null
                    ? signedUSD(resolvedPerformanceSummary.total_pnl)
                    : '--',
                  colorClass: resolvedPerformanceSummary != null
                    ? resolvedPerformanceSummary.total_pnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
                    : 'text-slate-900 dark:text-slate-100',
                },
                {
                  label: 'Win Rate',
                  value: resolvedPerformanceSummary != null && Number.isFinite(resolvedPerformanceSummary.win_rate) ? `${(resolvedPerformanceSummary.win_rate * 100).toFixed(1)}%` : '--',
                  colorClass: 'text-slate-900 dark:text-slate-100',
                },
                {
                  label: 'Best Trade',
                  value: resolvedPerformanceSummary != null ? signedUSD(resolvedPerformanceSummary.best_trade) : '--',
                  colorClass: 'text-emerald-500',
                },
                {
                  label: 'Worst Trade',
                  value: resolvedPerformanceSummary != null ? signedUSD(resolvedPerformanceSummary.worst_trade) : '--',
                  colorClass: 'text-rose-500',
                },
              ].map((cell) => (
                <div key={cell.label} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <p className={mutedClass}>{cell.label}</p>
                  <p className={cn('mt-1 text-sm font-mono tabular-nums font-semibold', cell.colorClass)}>{cell.value}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Equity Curve</p>
              </div>
              <EquityCurve orders={orders} />
            </div>
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Agent Matrix</p>
                <p className={mutedClass}>{sanitizeValue(realAgents.length)}</p>
              </div>
              {realAgents.length === 0 ? (
                <EmptyState message={wsConnected ? 'No active agents' : 'Connecting…'} />
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {realAgents.map((agent) => (
                    <div
                      key={agent.name}
                      className={cn(
                        'rounded-lg border p-3 transition-all duration-150 hover:shadow-sm',
                        agent.status === 'Live'
                          ? 'border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/20'
                          : agent.status === 'Error'
                            ? 'border-rose-200 bg-rose-50/30 dark:border-rose-900/30 dark:bg-rose-950/10'
                            : 'border-slate-200 dark:border-slate-800',
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-sans font-semibold text-slate-900 dark:text-slate-100">{displayAgentName(agent.name)}</p>
                        <div className="flex items-center gap-1.5">
                          <span className={cn(
                            'h-2 w-2 rounded-full',
                            agent.status === 'Live' ? 'animate-pulse bg-emerald-500' :
                            agent.status === 'Stale' ? 'bg-amber-400' :
                            agent.status === 'Error' ? 'bg-rose-500' : 'bg-slate-300 dark:bg-slate-600'
                          )} />
                          <span className={cn('text-xs font-mono font-semibold',
                            agent.status === 'Live' ? 'text-emerald-600 dark:text-emerald-400' :
                            agent.status === 'Stale' ? 'text-amber-600 dark:text-amber-400' :
                            agent.status === 'Error' ? 'text-rose-600 dark:text-rose-400' : 'text-slate-400'
                          )}>{agent.status}</span>
                        </div>
                      </div>
                      <div className="mt-2 flex items-center justify-between">
                        {(agent.realtimeCount + agent.persistedCount) > 0 ? (
                          <p className="text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                            {agent.realtimeCount + agent.persistedCount} events
                          </p>
                        ) : agent.lastSeen ? (
                          <p className={mutedClass}>active</p>
                        ) : (
                          <p className={mutedClass}>waiting</p>
                        )}
                        <p className={mutedClass}>
                          {agent.lastSeen ? formatTimeAgoSafe(agent.lastSeen) : '—'}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <p className={sectionTitleClass}>Live Market Prices</p>
              <div className="flex items-center gap-2">
                {pricesLoading ? (
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                    <span className="text-xs font-sans text-amber-500">Loading</span>
                  </div>
                ) : Object.keys(prices).length > 0 ? (
                  (() => {
                    // Derive freshness from the prices themselves rather than the
                    // market_ticks stream lag. When prices are hydrated via REST
                    // (cold start, WS not connected) the stream lag metric is
                    // null and would falsely display "Stale" while the tile
                    // dots show green. Pick the freshest updatedAt across all
                    // tiles and grade by that.
                    // /dashboard/state hydrates Redis payloads with `ts`
                    // (or `timestamp`) rather than `updatedAt`, so fall back
                    // to those before declaring a tile stale on cold start.
                    const ages = Object.values(prices)
                      .map((p) => {
                        const r = p as { updatedAt?: string | null; ts?: string | null; timestamp?: string | null }
                        return parseTimestamp(r?.updatedAt ?? r?.ts ?? r?.timestamp)
                      })
                      .filter((d): d is Date => d instanceof Date)
                      .map((d) => Date.now() - d.getTime())
                    const freshestMs = ages.length > 0 ? Math.min(...ages) : null
                    const isLive = freshestMs != null && freshestMs <= 60_000
                    return (
                      <div className="flex items-center gap-2">
                        <div className={cn('h-2 w-2 rounded-full', isLive ? 'bg-emerald-500' : 'bg-amber-500')} />
                        <span className={cn('text-xs font-sans', isLive ? 'text-emerald-500' : 'text-amber-500')}>
                          {isLive ? 'Live' : 'Stale'}
                        </span>
                      </div>
                    )
                  })()
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-slate-500" />
                    <span className="text-xs font-sans text-slate-500">No Data</span>
                  </div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {pricesLoading ? (
                // Show loading skeletons
                Array.from({ length: 6 }).map((_, index) => <PriceCardSkeleton key={`skeleton-${index}`} />)
              ) : (
                tickerEntries.map(([symbol, priceData]) => {
                  const price = toFiniteNumber(priceData?.price)
                  const previous = toFiniteNumber(priceData?.previousPrice)
                  const observedChange = toFiniteNumber(priceData?.change)
                  const change = observedChange ?? (price != null && previous != null ? price - previous : null)
                  const isPositive = (change ?? 0) >= 0
                  const hasData = price != null && !isNaN(price)
                  
                  return (
                    <div key={symbol} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <div className="flex items-center justify-between">
                        <p className={sectionTitleClass}>{sanitizeValue(symbol)}</p>
                        <div className={cn('h-2 w-2 rounded-full', hasData ? 'bg-emerald-500' : 'bg-slate-500')} />
                      </div>
                      <p className="mt-1 text-lg font-mono tabular-nums text-slate-900 dark:text-slate-100">
                        {hasData ? formatUSD(price) : '--'}
                      </p>
                      <div className="mt-2 flex items-center justify-between">
                        <p className={cn('text-xs font-mono tabular-nums', 
                          change == null || !hasData ? 'text-slate-500' : isPositive ? 'text-emerald-500' : 'text-rose-500'
                        )}>
                          {change == null || !hasData ? '--' : `${isPositive ? '▲' : '▼'} ${formatUSD(Math.abs(change))}`}
                        </p>
                        <p className={mutedClass}>{formatTimestamp((priceData?.updatedAt as string | null) ?? null)}</p>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}

      {section === 'trading' && (
        <TradingView
          setActiveTraceId={setActiveTraceId}
          tradeFeedEmptyReason={tradeFeedEmptyReason}
          tradeFeedUpstream={tradeFeedUpstream}
        />
      )}

      {section === 'agents' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div className={cardClass}>
              <p className={sectionTitleClass}>Market Ticks</p>
              <p className={valueClass}>{sanitizeValue(marketTickCount)}</p>
              <p className={mutedClass}>Last symbol: {lastMarketSymbol ?? '--'}</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Active Agents</p>
              <p className={valueClass}>{sanitizeValue(realAgents.filter((agent) => agent.status === 'Live').length)}</p>
              <p className={mutedClass}>Live heartbeat &lt; 10s</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Pipeline Events</p>
              <p className={valueClass}>{sanitizeValue(agentLogs.length)}</p>
              <p className={mutedClass}>Processed events (runtime)</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Notifications</p>
              <p className={valueClass}>{sanitizeValue(notifications.length)}</p>
              <p className={mutedClass}>
                {(() => {
                  const lastNotificationTime = parseTimestamp(notifications[0]?.timestamp)
                  return lastNotificationTime
                    ? `Last: ${lastNotificationTime.toLocaleTimeString()}`
                    : 'No activity yet'
                })()}
              </p>
            </div>
          </div>

          <LLMHealthPanel />

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-2')}>System Diagnostics</p>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
                  isInMemoryMode
                    ? 'bg-amber-400/10 text-amber-500'
                    : 'bg-emerald-500/10 text-emerald-500',
                )}
              >
                <span
                  className={cn(
                    'inline-block h-2 w-2 rounded-full',
                    isInMemoryMode ? 'bg-amber-400' : 'bg-emerald-500',
                  )}
                />
                {isInMemoryMode ? 'DB: In-Memory Fallback' : 'DB: Connected'}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <p className={mutedClass}>
                Heartbeats (in-memory/Redis): <span className="font-mono text-slate-700 dark:text-slate-200">{agentStatuses.length}</span>
                <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.heartbeatAgeMs)}</span>
              </p>
              <p className={mutedClass}>
                Lifecycle rows (DB): <span className="font-mono text-slate-700 dark:text-slate-200">{agentInstances.length}</span>
                <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.instanceAgeMs)}</span>
              </p>
              <p className={mutedClass}>
                Agent logs (DB/WS): <span className="font-mono text-slate-700 dark:text-slate-200">{agentLogs.length}</span>
                <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.logAgeMs)}</span>
              </p>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {[
                { label: 'dashboard/state', value: apiHealth.dashboardState },
                { label: 'agent-instances', value: apiHealth.agentInstances },
                { label: 'history/events', value: apiHealth.eventHistory },
              ].map((apiRow) => (
                <span
                  key={apiRow.label}
                  className={cn(
                    'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                    apiRow.value === 'ok'
                      ? 'bg-emerald-500/10 text-emerald-500'
                      : apiRow.value === 'error'
                        ? 'bg-rose-500/10 text-rose-500'
                        : 'bg-slate-500/10 text-slate-500',
                  )}
                >
                  {apiRow.label}: {apiRow.value}
                </span>
              ))}
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Status</p>
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800">
                    {['Agent', 'Status', 'Source', 'Events', 'Last Seen'].map((head) => (
                      <th key={head} className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{head}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {showNoAgentDataMessage ? (
                    <tr>
                      <td colSpan={5} className="px-2 py-8"><EmptyState message="No active agents" /></td>
                    </tr>
                  ) : (
                    realAgents.map((agent) => (
                      <tr key={agent.name} className="border-t border-slate-200 py-2 dark:border-slate-800">
                        <td className="px-2 py-2 text-sm font-sans text-slate-900 dark:text-slate-100">{displayAgentName(agent.name)}</td>
                        <td className="px-2 py-2 text-xs font-sans">
                          <span className="inline-flex items-center gap-2">
                            <span className={cn(
                              'h-2 w-2 rounded-full',
                              agent.status === 'Live'
                                ? 'bg-emerald-300'
                                : agent.status === 'Stale'
                                  ? 'bg-amber-300'
                                  : agent.status === 'Error'
                                    ? 'bg-rose-300'
                                    : 'bg-slate-400',
                            )} />
                            <span className="text-slate-700 dark:text-slate-300">{agent.status}</span>
                          </span>
                        </td>
                        <td className="px-2 py-2 text-xs font-sans text-slate-700 dark:text-slate-300">{formatAgentSource(agent.source)}</td>
                        <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                          {(agent.realtimeCount + agent.persistedCount) > 0 ? (
                            <>{(agent.realtimeCount + agent.persistedCount).toLocaleString()} events</>
                          ) : (
                            <span className="text-slate-400 dark:text-slate-600">—</span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{agent.lastSeen ? formatTimeAgoSafe(agent.lastSeen) : '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Instances</p>
            {agentInstances.length === 0 ? (
              <div className="space-y-2">
                <EmptyState message="No instances registered yet" />
                {agentStatuses.some((agent) => String(agent.status).toUpperCase() === 'ACTIVE') && (
                  <p className="text-xs font-sans text-amber-600 dark:text-amber-400">
                    Agents are reporting ACTIVE heartbeats, but no lifecycle records were returned. Check agent_instances DB writes.
                  </p>
                )}
              </div>
            ) : (
              <div className="max-h-48 overflow-y-auto">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800">
                      {['Instance Key', 'Pool', 'Status', 'Events', 'Uptime', 'Started'].map((head) => (
                        <th key={head} className="px-2 py-1.5 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{head}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {agentInstances.map((inst) => {
                      const isActive = inst.status === 'active'
                      return (
                        <tr key={inst.id} className="border-t border-slate-200 dark:border-slate-800">
                          <td className="px-2 py-1.5 text-xs font-mono text-slate-900 dark:text-slate-100">{inst.instance_key}</td>
                          <td className="px-2 py-1.5 text-xs font-sans text-slate-600 dark:text-slate-400">{inst.pool_name}</td>
                          <td className="px-2 py-1.5 text-xs font-sans">
                            <span className="inline-flex items-center gap-1.5">
                              <span className={cn('h-2 w-2 rounded-full', isActive ? 'bg-emerald-500' : 'bg-slate-400')} />
                              <span className={isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500'}>{inst.status}</span>
                            </span>
                          </td>
                          <td className="px-2 py-1.5 text-right text-xs font-mono tabular-nums text-slate-900 dark:text-slate-100">{inst.event_count}</td>
                          <td className="px-2 py-1.5 text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">{formatUptime(inst.uptime_seconds)}</td>
                          <td className="px-2 py-1.5 text-xs font-mono text-slate-500">{formatTimestamp(inst.started_at)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <RecentDecisionsPanel stats={decisionStats} recent={recentDecisions} />

          <NotificationFeed notifications={notifications} wsConnected={wsConnected} />
        </div>
      )}

      {section === 'learning' && <LearningDashboard />}

      {section === 'proposals' && <ProposalsSection />}

      {section === 'system' && (
        <div className="space-y-4">
          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>System Health</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Data latency</p>
                <p className="text-sm font-mono">{effectiveLatencyMs != null ? `${formatAgeFromMs(effectiveLatencyMs)} (${effectiveLatencyMs}ms)` : '--'}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Events/sec throughput</p>
                <p className="text-sm font-mono">{throughput.toFixed(2)}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Pipeline status</p>
                <p className={cn('text-sm font-semibold', pipelineStatus === 'Healthy' ? 'text-emerald-500' : pipelineStatus === 'Degraded' ? 'text-amber-500' : 'text-rose-500')}>{pipelineStatus}</p>
              </div>
            </div>
          </div>

          {pipelineWarning && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
              Signals generated but no orders placed
            </div>
          )}
          {!hasMarketData && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">
              No market data received
            </div>
          )}
          {hasMarketData && !latestTickTs && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
              Market events are arriving via WebSocket, but market_ticks lag metrics are missing.
            </div>
          )}
          {systemFeedError && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">
              {systemFeedError}
            </div>
          )}
          {!persistenceEnabled && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
              Persistence appears disabled (no persisted events/logs). Agents/Learning views may show incomplete history.
            </div>
          )}
          {llmAvailable === false && (
            <div className="rounded-lg border border-blue-500/40 bg-blue-500/10 p-3 text-sm text-blue-600 dark:text-blue-400">
              <span className="font-semibold">Rule-based mode</span> — no{' '}
              {llmProvider ? llmProvider.charAt(0).toUpperCase() + llmProvider.slice(1) : 'LLM'}{' '}
              API key configured. Reasoning decisions use signal direction only; set{' '}
              {llmProvider ? llmProvider.toUpperCase() + '_API_KEY' : 'an LLM API key'} to enable
              AI-powered analysis.
            </div>
          )}

          {/* ── Connection Diagnostics ── always visible so broken configs are obvious */}
          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Connection Diagnostics</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>WebSocket</p>
                <p className={cn('mt-1 text-sm font-semibold', wsConnected ? 'text-emerald-500' : 'text-rose-500')}>
                  {wsConnected ? '● Connected' : '● Disconnected'}
                </p>
                <p className="mt-1 break-all text-[10px] font-mono text-slate-400">
                  {typeof window !== 'undefined'
                    ? (process.env.NEXT_PUBLIC_WS_URL
                        ? process.env.NEXT_PUBLIC_WS_URL.replace(/^https?:\/\//, 'wss://').replace(/\/$/, '') + '/ws/dashboard'
                        : process.env.NEXT_PUBLIC_API_URL
                          ? process.env.NEXT_PUBLIC_API_URL.replace(/\/api\/?$/, '').replace(/^https?:\/\//, 'wss://') + '/ws/dashboard'
                          : window.location.host + '/ws/dashboard (same-origin)')
                    : '—'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>API Base</p>
                <p className="mt-1 break-all text-xs font-mono text-slate-700 dark:text-slate-300">
                  {process.env.NEXT_PUBLIC_API_URL ?? '/api (fallback)'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Prices / REST</p>
                <p className={cn('mt-1 text-sm font-semibold', Object.keys(prices).length > 0 ? 'text-emerald-500' : pricesFetched ? 'text-amber-500' : 'text-slate-400')}>
                  {Object.keys(prices).length > 0 ? `● ${Object.keys(prices).length} symbols` : pricesFetched ? '● Fetched – poller offline?' : '● Waiting…'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Reconnect attempts</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{wsDiagnostics.reconnectAttempts}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Message rate</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{Number.isFinite(wsDiagnostics.messageRate) ? wsDiagnostics.messageRate.toFixed(2) : '0.00'} /sec</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Messages received</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{wsMessageCount}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Last message</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{formatTimestamp(wsLastMessageTimestamp)}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Last error</p>
                <p className="text-xs font-mono text-slate-700 dark:text-slate-300">{wsDiagnostics.lastError ?? 'None'}</p>
              </div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>PnL Clarity</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Realized</p><p className="text-sm font-mono">{totalTrades === 0 ? '--' : signedUSD(realizedPnl)}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Unrealized</p><p className="text-sm font-mono">{positions.length === 0 ? '--' : signedUSD(unrealizedPnl)}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Session</p><p className="text-sm font-mono">{totalTrades === 0 && positions.length === 0 ? '--' : signedUSD(realizedPnl + unrealizedPnl)}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Total (DB)</p><p className="text-sm font-mono">{resolvedPerformanceSummary ? signedUSD(resolvedPerformanceSummary.total_pnl) : '--'}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Trades</p><p className="text-sm font-mono">{totalTrades}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Win rate</p><p className="text-sm font-mono">{totalTrades === 0 ? '--' : `${pnlWinRate.toFixed(1)}% (${wins}/${totalTrades})`}</p></div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Pipeline Handoff</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Signals (stream)</p><p className="text-sm font-mono">{signalsCount}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Orders</p><p className="text-sm font-mono">{ordersCount}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Executions</p><p className="text-sm font-mono">{executionsCount}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Signal Agent (RT)</p><p className="text-sm font-mono">{signalAgentRealtimeCount}</p></div>
            </div>
            <p className={cn(mutedClass, 'mt-2')}>
              Reasoning: <span className="font-mono">{reasoningAgentStatus}</span> → Execution: <span className="font-mono">{executionAgentStatus}</span>
            </p>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Pipeline Status</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {['market_ticks', 'signals', 'orders', 'executions', 'agent_logs', 'risk_alerts', 'notifications'].map((streamName) => {
                const stat = streamStats[streamName] ?? { count: 0, lastMessageTimestamp: null }
                const isLive = Boolean(stat.lastMessageTimestamp && Date.now() - new Date(stat.lastMessageTimestamp).getTime() < 60_000)
                return (
                  <div key={streamName} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">{streamName}</p>
                      <span className={cn('h-2 w-2 rounded-full', isLive ? 'bg-emerald-500' : 'bg-slate-500')} />
                    </div>
                    <p className="mt-1 text-lg font-mono tabular-nums text-slate-900 dark:text-slate-100">{stat.count}</p>
                  </div>
                )
              })}
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Recent Events</p>
            {recentEvents.length === 0 ? (
              <EmptyState message={wsConnected ? 'No websocket events yet' : 'Stream disconnected'} />
            ) : (
              <div className="space-y-2">
                {recentEvents.map((event, index) => (
                  <div key={`${event.stream ?? 'evt'}-${event.timestamp ?? ''}-${event.msgId !== 'n/a' ? (event.msgId ?? index) : index}`} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                    <span
                      className={cn(
                        'rounded px-2 py-0.5 text-xs font-semibold',
                        event.stream === 'market_ticks'
                          ? 'bg-emerald-500/15 text-emerald-500'
                          : event.stream === 'signals'
                            ? 'bg-slate-500/10 text-slate-500'
                            : event.stream === 'orders'
                              ? 'bg-amber-500/15 text-amber-500'
                              : 'bg-slate-500/15 text-slate-500'
                      )}
                    >
                      {event.stream}
                    </span>
                    <span className="text-xs font-mono text-slate-500">{event.msgId && event.msgId !== 'n/a' ? event.msgId.slice(0, 10) : '--'}</span>
                    <span className="text-xs font-mono text-slate-500">{formatTimestamp(event.timestamp)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Observability</p>
            {agentStatuses.length === 0 ? (
              <EmptyState message="No agent status yet" icon={Brain} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-slate-500"><th className="pb-2">Agent</th><th>Status</th><th>Signals</th><th>Last action</th></tr></thead>
                  <tbody>
                    {agentStatuses.map((agent) => (
                      <tr key={agent.name} className="border-t border-slate-200 dark:border-slate-800">
                        <td className="py-2 font-semibold">{agent.name}</td>
                        <td>{agent.status}</td>
                        <td className="font-mono">{agent.event_count}</td>
                        <td>{agent.last_event || '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Persisted Event History</p>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={cn(mutedClass, 'mb-2')}>Processed counts by stream</p>
                {persistedCounts.length === 0 ? (
                  <p className={mutedClass}>{isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'}</p>
                ) : (
                  <div className="space-y-1">
                    {persistedCounts.slice(0, 8).map((row) => (
                      <div key={row.stream} className="flex items-center justify-between text-xs font-mono">
                        <span className="text-slate-600 dark:text-slate-300">{row.stream}</span>
                        <span className="text-slate-900 dark:text-slate-100">{row.processed_count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={cn(mutedClass, 'mb-2')}>Latest persisted events</p>
                {persistedEvents.length === 0 ? (
                  <p className={mutedClass}>{isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'}</p>
                ) : (
                  <div className="space-y-1">
                    {persistedEvents.slice(0, 8).map((evt) => (
                      <div key={evt.id} className="flex items-center justify-between text-xs font-mono">
                        <span className="text-slate-600 dark:text-slate-300">{sanitizeValue(evt.kind)}</span>
                        <span className="text-slate-500">{formatTimestamp(evt.created_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <p className={cn(mutedClass, 'mb-2')}>Latest persisted agent logs</p>
              {persistedLogs.length === 0 ? (
                <p className={mutedClass}>{isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'}</p>
              ) : (
                <div className="space-y-1">
                  {persistedLogs.slice(0, 10).map((log) => (
                    <button
                      key={log.id}
                      type="button"
                      className="flex w-full items-center justify-between rounded px-1 py-1 text-left text-xs font-mono hover:bg-slate-100 dark:hover:bg-slate-800"
                      onClick={() => log.trace_id && setActiveTraceId(log.trace_id)}
                    >
                      <span className="text-slate-600 dark:text-slate-300">{sanitizeValue(log.kind)}</span>
                      <span className="text-slate-500">{formatTimestamp(log.created_at)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )

  return (
    <div className="min-h-screen bg-slate-100 pb-20 dark:bg-slate-950 lg:pb-4">
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div
          className={cn(
            'rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-widest',
            systemStatus === 'trading'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300'
              : systemStatus === 'booting'
                ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300'
                : systemStatus === 'error'
                  ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300'
                  : 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
          )}
        >
          System Status: {systemStatus}
        </div>
        {/* Persistence / memory-mode banner — single page-level indicator */}
        {dashboardData?.degraded_mode && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-300">
            <span className="mt-0.5 shrink-0">⚠</span>
            <span>
              <strong>Memory mode</strong> — database unavailable
              {dashboardData.degraded_reason === 'db_unavailable' ? ': PostgreSQL unreachable' : ''}.
              Data is ephemeral and will be lost on restart. Trade history and grades are stored in-process only.
            </span>
          </div>
        )}
        {contentBySection}
      </main>

      {activeTraceId && (
        <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />
      )}
    </div>
  )
}
