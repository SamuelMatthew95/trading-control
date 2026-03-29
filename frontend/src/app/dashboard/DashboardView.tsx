'use client'

import { useCallback, useEffect, useMemo, useState, type ComponentType } from 'react'
import { cn } from '@/lib/utils'
import {
  Activity,
  BarChart3,
  Brain,
  FileCode,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { useCodexStore } from '@/stores/useCodexStore'
import { LiveMarketPrices } from '@/components/dashboard/LiveMarketPrices'
import { AgentMatrix } from '@/components/dashboard/AgentMatrix'

const sanitizeValue = (value: string | number | boolean | null | undefined): string => {
  if (value === undefined || value === null || value === '') return '--';
  if (typeof value === 'number' && (isNaN(value) || !isFinite(value))) return '--';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  return String(value);
};

const toSanitizeInput = (value: unknown): string | number | boolean | null | undefined => {
  if (value === null || value === undefined) return value
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  return String(value)
}

const formatUSD = (value?: number | null): string => {
  if (value == null || isNaN(value) || !isFinite(value)) return '$0.00';
  return `$${Math.abs(value).toFixed(2)}`;
};

const formatTimeAgo = (date: Date): string => {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
};

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}

const cardClass = 'rounded-xl border border-slate-200 bg-white p-4 transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600 sm:p-5'
const sectionTitleClass = 'text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400'
const mutedClass = 'text-xs font-sans text-slate-500 dark:text-slate-400'
const valueClass = 'text-2xl font-black font-mono tabular-nums text-slate-950 dark:text-slate-100'

type Section = 'overview' | 'trading' | 'agents' | 'learning' | 'system'

type AgentSummary = {
  name: string
  count: number
  lastSeen: Date | null
  status: 'ACTIVE' | 'IDLE' | 'WAITING'
  tier: 'active' | 'challenger' | 'inactive'
}

const TRACKED_AGENTS = [
  'SIGNAL_AGENT',
  'REASONING_AGENT',
  'GRADE_AGENT',
  'IC_UPDATER',
  'REFLECTION_AGENT',
  'STRATEGY_PROPOSER',
  'NOTIFICATION_AGENT',
] as const

const TICKER_SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AAPL', 'TSLA', 'SPY'] as const

function toFiniteNumber(value: unknown): number | null {
  const cast = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(cast) ? cast : null
}

function getMetric(systemMetrics: Array<Record<string, unknown>>, metricName: string): number | null {
  const match = systemMetrics.find((metric) => metric?.metric_name === metricName)
  return toFiniteNumber(match?.value)
}

function EmptyState({ message, icon: Icon }: { message: string; icon: ComponentType<{ className?: string }> }) {
  return (
    <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed border-slate-300 px-4 py-10 dark:border-slate-700">
      <div className="flex flex-col items-center gap-2 text-center">
        <Icon className="h-5 w-5 text-slate-400" />
        <p className="text-sm font-sans text-slate-400">{message}</p>
      </div>
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

function EquityCurve({ orders }: { orders: Array<Record<string, unknown>> }) {
  const points = useMemo(() => {
    let running = 0
    return orders.map((order, index) => {
      running += toFiniteNumber(order?.pnl) ?? 0
      return { x: index, y: running }
    })
  }, [orders])

  if (points.length === 0) {
    return <EmptyState message="No equity data yet" icon={BarChart3} />
  }

  const maxY = Math.max(...points.map((point) => point.y), 0)
  const minY = Math.min(...points.map((point) => point.y), 0)
  const range = maxY - minY || 1
  const chartPoints = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 100
      const y = 100 - ((point.y - minY) / range) * 100
      return `${x},${y}`
    })
    .join(' ')

  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <svg viewBox="0 0 100 100" className="h-48 w-full">
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-emerald-500"
          points={chartPoints}
        />
      </svg>
    </div>
  )
}

function MobileNavigation({ section }: { section: Section }) {
  const links: { key: Section; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'trading', label: 'Trading' },
    { key: 'agents', label: 'Agents' },
    { key: 'learning', label: 'Learning' },
    { key: 'system', label: 'System' },
  ]

  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-slate-100/95 px-2 py-2 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 lg:hidden">
      <div className="mx-auto grid max-w-7xl grid-cols-5 gap-1">
        {links.map((link) => (
          <div
            key={link.key}
            className={cn(
              'flex min-h-11 items-center justify-center rounded-lg px-2 text-xs font-sans font-semibold',
              section === link.key
                ? 'bg-slate-900 text-slate-100 dark:bg-slate-100 dark:text-slate-900'
                : 'text-slate-500 dark:text-slate-400'
            )}
          >
            {link.label}
          </div>
        ))}
      </div>
    </nav>
  )
}

export function DashboardView({ section }: { section: Section }) {
  // Legacy data for non-realtime components
  const {
    orders = [],
    positions = [],
    systemMetrics = [],
    dashboardData,
    learningEvents = [],
    agentLogs = [],
    marketTickCount = 0,
    lastMarketSymbol = null,
    streamStats = {},
    wsMessageCount = 0,
    wsLastMessageTimestamp = null,
    recentEvents = [],
    wsConnected = false,
  } = useCodexStore()

  const [showNoAgentDataMessage, setShowNoAgentDataMessage] = useState(false)

  const formatTimeAgoSafe = useCallback((date: Date) => formatTimeAgo(date), [])
  
  const realAgents = useMemo(() => {
    const grouped = agentLogs.reduce<Record<string, { count: number; lastSeen: Date | null }>>((acc, log) => {
      const name = sanitizeValue(log?.agent_name || log?.agent)
      if (name === '--') return acc
      const timestamp = new Date(String(log?.timestamp || log?.created_at || ''))
      const safeDate = Number.isNaN(timestamp.getTime()) ? null : timestamp
      const existing = acc[name] ?? { count: 0, lastSeen: null }
      const newest = !existing.lastSeen || (safeDate && safeDate > existing.lastSeen) ? safeDate : existing.lastSeen
      acc[name] = { count: existing.count + 1, lastSeen: newest }
      return acc
    }, {})

    const now = Date.now()
    const incomingAgents = Object.entries(grouped).map<AgentSummary>(([name, data]) => {
      const ageMs = data.lastSeen ? now - data.lastSeen.getTime() : Infinity
      const status: AgentSummary['status'] = ageMs < 5 * 60 * 1000 ? 'ACTIVE' : 'IDLE'
      const tier: AgentSummary['tier'] = status === 'ACTIVE' ? 'active' : data.count > 0 ? 'challenger' : 'inactive'
      return { name, count: data.count, lastSeen: data.lastSeen, status, tier }
    })

    const normalizedByName = new Map(incomingAgents.map((agent) => [agent.name, agent]))
    for (const name of TRACKED_AGENTS) {
      if (!normalizedByName.has(name)) {
        normalizedByName.set(name, {
          name,
          count: 0,
          lastSeen: null,
          status: 'WAITING',
          tier: 'inactive',
        })
      }
    }

    return Array.from(normalizedByName.values())
  }, [agentLogs])

  const summary = useMemo(() => {
    const dailyPnlNumeric = orders.reduce((sum, order) => sum + (toFiniteNumber(order?.pnl) ?? 0), 0)
    const wins = orders.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) > 0).length
    const winRate = orders.length > 0 ? (wins / orders.length) * 100 : null
    const activePositions = positions.filter((position) => position?.side === 'long' || position?.side === 'short').length
    const dailyChangeFromMetric = getMetric(systemMetrics, 'daily_change_pct')
    const dailyChangeFromDashboard = toFiniteNumber((dashboardData as Record<string, unknown> | null)?.['daily_change_pct'])
    const dailyChange = dailyChangeFromMetric ?? dailyChangeFromDashboard

    return {
      dailyPnlNumeric,
      winRate,
      activePositions,
      dailyChange,
      hasOrders: orders.length > 0,
    }
  }, [orders, positions, systemMetrics, dashboardData])

  const learningSummary = useMemo(() => {
    const tradesEvaluated = learningEvents.filter((event) => event?.type === 'trade_evaluated').length
    const reflectionsCompleted = learningEvents.filter((event) => event?.type === 'reflection').length
    const icValuesUpdated = learningEvents.filter((event) => event?.type === 'ic_update').length
    const strategiesTested = learningEvents.filter((event) => event?.type === 'strategy_tested').length

    const dailyPnlMap = orders.reduce<Record<string, number>>((acc, order) => {
      const timestamp = new Date(String(order?.timestamp || ''))
      if (Number.isNaN(timestamp.getTime())) return acc
      const key = timestamp.toDateString()
      acc[key] = (acc[key] ?? 0) + (toFiniteNumber(order?.pnl) ?? 0)
      return acc
    }, {})

    const dayEntries = Object.entries(dailyPnlMap)
    const bestDay = dayEntries.length > 0 ? dayEntries.reduce((best, current) => (current[1] > best[1] ? current : best)) : null
    const worstDay = dayEntries.length > 0 ? dayEntries.reduce((worst, current) => (current[1] < worst[1] ? current : worst)) : null

    return {
      tradesEvaluated,
      reflectionsCompleted,
      icValuesUpdated,
      strategiesTested,
      bestDay,
      worstDay,
    }
  }, [learningEvents, orders])


  const contentBySection = (
    <>
      {section === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { title: 'Daily P&L', value: summary.hasOrders ? `${summary.dailyPnlNumeric >= 0 ? '+' : '-'}${formatUSD(summary.dailyPnlNumeric)}` : '--', trend: summary.hasOrders ? (summary.dailyPnlNumeric > 0 ? 1 : summary.dailyPnlNumeric < 0 ? -1 : 0) : 0 },
              { title: 'Win Rate', value: summary.winRate == null ? '--' : `${sanitizeValue(summary.winRate.toFixed(2))}%`, trend: 0 },
              { title: 'Active Positions', value: sanitizeValue(summary.activePositions), trend: 0 },
              { title: 'Daily Change %', value: summary.dailyChange == null ? 'N/A' : `${sanitizeValue(summary.dailyChange.toFixed(2))}%`, trend: summary.dailyChange == null ? 0 : summary.dailyChange > 0 ? 1 : summary.dailyChange < 0 ? -1 : 0 },
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

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Equity Curve</p>
              </div>
              <EquityCurve orders={orders} />
            </div>
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <AgentMatrix />
            </div>
          </div>

          <LiveMarketPrices />
        </div>
      )}

      {section === 'trading' && (
        <div className="space-y-4">
          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <p className={sectionTitleClass}>Agent Thought Stream</p>
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
                <span className={mutedClass}>LIVE</span>
              </div>
            </div>
            {agentLogs.length === 0 ? (
              <EmptyState message="No agent activity yet" icon={Activity} />
            ) : (
              <div className="relative max-h-80 overflow-y-auto">
                <div className="space-y-2">
                  {agentLogs.slice(-10).reverse().map((log, index) => {
                    const confidence = toFiniteNumber(log?.confidence)
                    const confidencePct = confidence == null ? '--' : sanitizeValue((confidence * 100).toFixed(0))
                    const confidenceClass = confidence != null && confidence > 0.9 ? 'bg-emerald-500/15 text-emerald-500' : confidence != null && confidence >= 0.75 ? 'bg-amber-500/15 text-amber-500' : 'bg-slate-500/15 text-slate-500'
                    return (
                      <div key={`${sanitizeValue(log?.timestamp)}-${index}`} className="border-t border-slate-200 py-2 first:border-t-0 dark:border-slate-800">
                        <div className="mb-1 flex items-center gap-2">
                          <p className="text-sm font-sans font-bold text-slate-900 dark:text-slate-100">{sanitizeValue(toSanitizeInput(log?.agent_name || log?.agent)) === '--' ? 'N/A' : sanitizeValue(toSanitizeInput(log?.agent_name || log?.agent))}</p>
                          <span className={cn('rounded px-2 py-0.5 text-xs font-sans font-semibold', confidenceClass)}>{confidencePct}%</span>
                        </div>
                        <p className="text-sm font-sans leading-relaxed text-slate-700 dark:text-slate-300">{sanitizeValue(toSanitizeInput(log?.message || log?.summary || log?.primary_edge)) === '--' ? 'N/A' : sanitizeValue(toSanitizeInput(log?.message || log?.summary || log?.primary_edge))}</p>
                      </div>
                    )
                  })}
                </div>
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-white to-transparent dark:from-slate-900" />
              </div>
            )}
          </div>

          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <p className={sectionTitleClass}>Open Positions</p>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr className="border-b border-slate-200 pb-2 dark:border-slate-800">
                    {['Symbol', 'Side', 'Qty', 'Entry Price', 'Current Price', 'P&L', 'P&L %'].map((head) => (
                      <th key={head} className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{head}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-2 py-8"><EmptyState message="No open positions" icon={BarChart3} /></td>
                    </tr>
                  ) : (
                    positions.map((position, index) => {
                      const pnl = toFiniteNumber(position?.pnl)
                      const pnlPct = toFiniteNumber(position?.pnl_pct)
                      const isPositive = (pnl ?? 0) >= 0
                      const side = sanitizeValue(position?.side).toUpperCase()
                      return (
                        <tr key={`${sanitizeValue(position?.symbol)}-${index}`} className="border-t border-slate-200 py-2 dark:border-slate-800">
                          <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{sanitizeValue(position?.symbol)}</td>
                          <td className="px-2 py-2">
                            <span className={cn('rounded px-2 py-0.5 text-xs font-sans font-semibold', side === 'LONG' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-rose-500/15 text-rose-500')}>
                              {side === '--' ? 'N/A' : side}
                            </span>
                          </td>
                          <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{sanitizeValue(toSanitizeInput(position?.qty))}</td>
                          <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{toFiniteNumber(position?.entry_price) == null ? '--' : formatUSD(toFiniteNumber(position?.entry_price))}</td>
                          <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{toFiniteNumber(position?.current_price) == null ? '--' : formatUSD(toFiniteNumber(position?.current_price))}</td>
                          <td className={cn('px-2 py-2 text-right text-sm font-mono tabular-nums font-bold', isPositive ? 'text-emerald-500' : 'text-rose-500')}>
                            {pnl == null ? '--' : `${isPositive ? '+' : '-'}${formatUSD(pnl)}`}
                          </td>
                          <td className={cn('px-2 py-2 text-right text-xs font-mono tabular-nums', isPositive ? 'text-emerald-500' : 'text-rose-500')}>
                            {pnlPct == null ? '--' : `${sanitizeValue(pnlPct.toFixed(2))}%`}
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {section === 'agents' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className={cardClass}>
              <p className={sectionTitleClass}>Market Ticks</p>
              <p className={valueClass}>{sanitizeValue(marketTickCount)}</p>
              <p className={mutedClass}>Last symbol: {lastMarketSymbol ?? '--'}</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Tracked Agents</p>
              <p className={valueClass}>{TRACKED_AGENTS.length}</p>
              <p className={mutedClass}>Pre-populated on connect</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Agent Events</p>
              <p className={valueClass}>{sanitizeValue(agentLogs.length)}</p>
              <p className={mutedClass}>Total events received</p>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Status</p>
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800">
                    {['Agent', 'Status', 'Events', 'Last Seen'].map((head) => (
                      <th key={head} className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{head}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {showNoAgentDataMessage ? (
                    <tr>
                      <td colSpan={4} className="px-2 py-8"><EmptyState message="No agent data available" icon={Activity} /></td>
                    </tr>
                  ) : (
                    realAgents.map((agent) => (
                      <tr key={agent.name} className="border-t border-slate-200 py-2 dark:border-slate-800">
                        <td className="px-2 py-2 text-sm font-sans text-slate-900 dark:text-slate-100">{sanitizeValue(agent.name)}</td>
                        <td className="px-2 py-2 text-xs font-sans">
                          <span className="inline-flex items-center gap-2">
                            <span className={cn('h-2 w-2 rounded-full', agent.status === 'ACTIVE' ? 'animate-pulse bg-emerald-500' : 'bg-slate-500')} />
                            <span className="text-slate-700 dark:text-slate-300">{agent.status.toLowerCase()}</span>
                          </span>
                        </td>
                        <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{sanitizeValue(agent.count)}</td>
                        <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{agent.lastSeen ? formatTimeAgoSafe(agent.lastSeen) : '--'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {section === 'learning' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
            {[
              { label: 'Trades Evaluated', value: learningSummary.tradesEvaluated, Icon: FileCode, color: 'text-indigo-500' },
              { label: 'Reflections Completed', value: learningSummary.reflectionsCompleted, Icon: Brain, color: 'text-violet-500' },
              { label: 'IC Values Updated', value: learningSummary.icValuesUpdated, Icon: Activity, color: 'text-indigo-500' },
              { label: 'Strategies Tested', value: learningSummary.strategiesTested, Icon: Zap, color: 'text-violet-500' },
            ].map((item) => (
              <div key={item.label} className={cardClass}>
                <div className="mb-3 flex items-center justify-between">
                  <p className={sectionTitleClass}>{item.label}</p>
                  <item.Icon className={cn('h-4 w-4', item.color)} />
                </div>
                <p className={valueClass}>{sanitizeValue(item.value)}</p>
              </div>
            ))}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Performance Summary</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Win Rate</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{summary.winRate == null ? '--' : `${sanitizeValue(summary.winRate.toFixed(2))}%`}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Total P&L</p>
                <p className={cn('text-sm font-mono tabular-nums', summary.dailyPnlNumeric >= 0 ? 'text-emerald-500' : 'text-rose-500')}>
                  {summary.hasOrders ? `${summary.dailyPnlNumeric >= 0 ? '+' : '-'}${formatUSD(summary.dailyPnlNumeric)}` : '--'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Best Day</p>
                <p className="text-sm font-mono tabular-nums text-emerald-500">
                  {learningSummary.bestDay ? `${learningSummary.bestDay[0]} (${learningSummary.bestDay[1] >= 0 ? '+' : '-'}${formatUSD(learningSummary.bestDay[1])})` : 'N/A'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Worst Day</p>
                <p className="text-sm font-mono tabular-nums text-rose-500">
                  {learningSummary.worstDay ? `${learningSummary.worstDay[0]} (${learningSummary.worstDay[1] >= 0 ? '+' : '-'}${formatUSD(learningSummary.worstDay[1])})` : 'N/A'}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {section === 'system' && (
        <div className="space-y-4">
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
            <p className={cn(sectionTitleClass, 'mb-3')}>WebSocket Status</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Connection</p>
                <p className={cn('text-sm font-semibold', wsConnected ? 'text-emerald-500' : 'text-slate-500')}>{wsConnected ? 'Connected' : 'Disconnected'}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Messages Received</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{wsMessageCount}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Last Message</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{formatTimestamp(wsLastMessageTimestamp)}</p>
              </div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Recent Events</p>
            {recentEvents.length === 0 ? (
              <EmptyState message="No websocket events yet" icon={Activity} />
            ) : (
              <div className="space-y-2">
                {recentEvents.map((event, index) => (
                  <div key={`${event.msgId}-${index}`} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                    <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', event.stream === 'market_ticks' ? 'bg-emerald-500/15 text-emerald-500' : event.stream === 'signals' ? 'bg-indigo-500/15 text-indigo-400' : event.stream === 'orders' ? 'bg-amber-500/15 text-amber-500' : 'bg-slate-500/15 text-slate-400')}>
                      {event.stream}
                    </span>
                    <span className="text-xs font-mono text-slate-500">{event.msgId.slice(0, 10)}</span>
                    <span className="text-xs font-mono text-slate-500">{formatTimestamp(event.timestamp)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )

  return (
    <div className="min-h-screen bg-slate-50 pb-20 dark:bg-slate-950 lg:pb-4">
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        {contentBySection}
      </main>

      <MobileNavigation section={section} />
    </div>
  )
}
