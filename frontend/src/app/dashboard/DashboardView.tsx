'use client'

import { useCallback, useMemo, useState, type ComponentType, type ReactNode } from 'react'
import { useCodexStore, type AgentStatus } from '@/stores/useCodexStore'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { useRestPoll } from '@/hooks/useRestPoll'
import { useLivePnl } from '@/hooks/useLivePnl'
import { useLivePositions } from '@/hooks/useLivePositions'
import { useLiveEquitySeries } from '@/hooks/useLiveEquitySeries'
import { cn } from '@/lib/utils'
import { formatUSD, signedUSD, formatTimeAgo, toFiniteNum as toFiniteNumber, sanitizeValue, formatTimestamp, isActivePosition, pricesFreshnessMs } from '@/lib/formatters'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { LearningConsole } from '@/components/dashboard/LearningConsole'
import { LiveNumber, LiveDot } from '@/components/dashboard/LiveNumber'
import { OpenPositionsPanel } from '@/components/dashboard/OpenPositionsPanel'
import { TradingView } from '@/components/dashboard/TradingView'
import { TraceModal } from '@/components/dashboard/TraceModal'
import { ProposalsSection } from '@/components/dashboard/ProposalsSection'
import { LLMDegradedBanner } from '@/components/dashboard/LLMDegradedBanner'
import { SystemDashboard } from '@/components/dashboard/system'
import { AgentsDashboard } from '@/components/dashboard/agents'
import { ALL_AGENT_NAMES, agentDisplayName, canonicalAgentKey } from '@/constants/agents'
import type { AgentSummary } from '@/lib/agent-pipeline'
import { isLifecycleLog } from '@/lib/activity-timeline'
import { cardClass, sectionTitleClass, mutedClass, valueClass } from '@/lib/dashboard-styles'
import {
  agentCardBorderClass,
  agentCardDotClass,
  agentCardTextClass,
  systemStatusBadgeClass,
  priceChangeTextClass,
  agentTierFromStatus,
  performancePnlColorClass,
} from '@/lib/dashboard-helpers'
import {
  TrendingDown,
  TrendingUp,
} from 'lucide-react'

type Section = 'overview' | 'trading' | 'agents' | 'learning' | 'proposals' | 'system'

type PerformanceCell = {
  label: 'Realized P&L' | 'Win Rate' | 'Best Trade' | 'Worst Trade'
  value: string
  colorClass: string
}



const SECTION_META: Record<Section, { eyebrow: string; title: string; description: string }> = {
  overview: {
    eyebrow: 'Operations overview',
    title: 'Portfolio and execution snapshot',
    description: 'Live prices, P&L, agent status, and recent activity in one view.',
  },
  trading: {
    eyebrow: 'Execution',
    title: 'Trades, fills, and traceable execution',
    description: 'Monitor open risk, fills, grades, and execution provenance without decorative cards.',
  },
  agents: {
    eyebrow: 'Runtime agents',
    title: 'Agent health and production activity',
    description: 'Inspect agent heartbeats, streams, decisions, and diagnostics in a dense operations layout.',
  },
  learning: {
    eyebrow: 'Learning loop',
    title: 'Performance attribution and learning outcomes',
    description: 'Review outcomes, model performance, and learning-loop movement with clear evidence.',
  },
  proposals: {
    eyebrow: 'Proposal review',
    title: 'Candidate changes and challenger verdicts',
    description: 'Approve or reject strategy mutations from a table-first queue with explicit expected impact.',
  },
  system: {
    eyebrow: 'Command Center',
    title: 'Decisions, risk, execution, and traceability',
    description: 'A live view of what the system is thinking, doing, and changing right now.',
  },
}

function SectionHeader({ section }: { section: Section }) {
  const meta = SECTION_META[section]
  return (
    <section className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm shadow-slate-900/5 dark:border-slate-800/80 dark:bg-slate-950/90 dark:shadow-black/20">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{meta.eyebrow}</p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">{meta.title}</h1>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">{meta.description}</p>
        </div>
      </div>
    </section>
  )
}

const TICKER_SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AAPL', 'TSLA', 'SPY'] as const
// Liveness window mirrors the backend heartbeat contract (api/constants.py):
//   AGENT_STALE_THRESHOLD_SECONDS = 120 → an agent stays "Live" while its last
//     heartbeat is < 2 min old. Agents heartbeat every 15–60s.
// Agent status is intentionally binary — Live (recent heartbeat) or Idle (not).
// The old amber "Stale" middle state was removed: it confused operators and
// contradicted the "active" Agent Instances table right next to it.
const AGENT_LIVE_THRESHOLD_MS = 120_000

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

// Last-resort equity base for the Daily Change % tile when the backend emits no
// portfolio_value / equity / starting_equity system metric. Mirrors the backend
// paper starting capital (DEFAULT_PAPER_CASH = $100k); a live metric is always
// preferred over this constant when present.
const DEFAULT_PAPER_EQUITY = 100_000

function getMetric(systemMetrics: Array<Record<string, unknown>>, metricName: string): number | null {
  const match = systemMetrics.find((metric) => metric?.metric_name === metricName)
  return toFiniteNumber(match?.value)
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

// ── Timing thresholds ─────────────────────────────────────────────────────────

const PRICE_FRESHNESS_MS = 60_000

function priceChangeText(change: number | null, hasData: boolean): string {
  if (change == null || !hasData) return '--'
  if (change === 0) return `→ ${formatUSD(0)}`
  return `${change > 0 ? '▲' : '▼'} ${formatUSD(Math.abs(change))}`
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function formatWinRate(rate: number | null, hasClosedTrades: boolean): string {
  if (rate == null || !Number.isFinite(rate)) return '--'
  return `${rate.toFixed(2)}%${hasClosedTrades ? '' : ' (open only)'}`
}

// Dead-band |change| < 0.005% to a clean "0.00%" so a tiny non-zero P&L on a
// large equity base never renders the "-0.00%"/"+0.00%" artifact.
const DAILY_CHANGE_DEADBAND_PCT = 0.005

function formatDailyChange(change: number | null | undefined): string {
  if (typeof change !== 'number' || !Number.isFinite(change)) return '--'
  if (Math.abs(change) < DAILY_CHANGE_DEADBAND_PCT) return '0.00%'
  const sign = change > 0 ? '+' : ''
  return `${sign}${change.toFixed(2)}%`
}

type PerformanceSummarySource = 'api' | 'local_closed_trades' | 'none'
type PerformanceSummaryLike = {
  total_pnl?: number | null
  win_rate?: number | null
  best_trade?: number | null
  worst_trade?: number | null
}

const TINY_BEST_TRADE_THRESHOLD = 0.05
const TINY_BEST_TRADE_BASE_TEXT = 'tiny gains (for example +$0.01) are valid execution data.'
const PERFORMANCE_SOURCE_PREFIX: Record<PerformanceSummarySource, ((closedTradeCount: number) => string) | null> = {
  api: () => 'From API trade history aggregate;',
  local_closed_trades: (closedTradeCount) => `From ${closedTradeCount} closed trade${closedTradeCount === 1 ? '' : 's'};`,
  none: null,
}

function formatWinRatePercent(rate: number | null | undefined): string {
  if (typeof rate !== 'number' || !Number.isFinite(rate)) return '--'
  return `${(rate * 100).toFixed(1)}%`
}

function getTinyBestTradeExplanation(
  bestTrade: number | null | undefined,
  source: PerformanceSummarySource,
  closedTradeCount: number,
): string | null {
  const isTinyPositive = Number.isFinite(bestTrade) && bestTrade != null && bestTrade > 0 && bestTrade < TINY_BEST_TRADE_THRESHOLD
  if (!isTinyPositive) return null
  const prefixBuilder = PERFORMANCE_SOURCE_PREFIX[source]
  const prefix = prefixBuilder ? prefixBuilder(closedTradeCount) : ''
  return `${prefix}${prefix ? ' ' : ''}${TINY_BEST_TRADE_BASE_TEXT}`
}

function buildPerformanceCells(summary: PerformanceSummaryLike | null): PerformanceCell[] {
  return [
    {
      // Realized P&L from graded/closed trades (DB or local fallback) — distinct
      // from the live "Total P&L" headline, which also includes open-position
      // unrealized. Labelled honestly so the two never read as contradictory.
      label: 'Realized P&L',
      value: summary != null ? signedUSD(summary.total_pnl) : '--',
      colorClass: performancePnlColorClass(summary?.total_pnl ?? null),
    },
    {
      label: 'Win Rate',
      value: summary != null ? formatWinRatePercent(summary.win_rate) : '--',
      colorClass: 'text-slate-900 dark:text-slate-100',
    },
    {
      label: 'Best Trade',
      value: summary != null ? signedUSD(summary.best_trade) : '--',
      colorClass: 'text-emerald-500',
    },
    {
      label: 'Worst Trade',
      value: summary != null ? signedUSD(summary.worst_trade) : '--',
      colorClass: 'text-rose-500',
    },
  ]
}

// ── Small UI-only components ──────────────────────────────────────────────────

type StatusDotProps = { live: boolean; label: string; loadingLabel?: string; loading?: boolean }
function StatusDot({ live, label, loading }: StatusDotProps) {
  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
        <span className="text-xs font-sans text-amber-500">Loading</span>
      </div>
    )
  }
  const color = live ? 'bg-emerald-500' : 'bg-amber-500'
  const text = live ? 'text-emerald-500' : 'text-amber-500'
  return (
    <div className="flex items-center gap-2">
      <div className={cn('h-2 w-2 rounded-full', color)} />
      <span className={cn('text-xs font-sans', text)}>{label}</span>
    </div>
  )
}

function PriceFreshnessStatus({
  prices,
  loading,
}: {
  prices: Record<string, unknown>
  loading: boolean
}) {
  if (loading) return <StatusDot live={false} label="" loading />

  const priceValues = Object.values(prices)
  if (priceValues.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-2 w-2 rounded-full bg-slate-500" />
        <span className="text-xs font-sans text-slate-500">No Data</span>
      </div>
    )
  }

  const freshestMs = priceValues
    .map((p) => {
      const r = p as { updatedAt?: string | null; ts?: string | null; timestamp?: string | null }
      return parseTimestamp(r?.updatedAt ?? r?.ts ?? r?.timestamp)
    })
    .filter((d): d is Date => d instanceof Date)
    .map((d) => Date.now() - d.getTime())
    .reduce((min, ms) => Math.min(min, ms), Infinity)

  const isLive = Number.isFinite(freshestMs) && freshestMs <= PRICE_FRESHNESS_MS
  return <StatusDot live={isLive} label={isLive ? 'Live' : 'Offline'} />
}

export function DashboardView({ section }: { section: Section }) {
  const {
    agentLogs = [],
    orders = [],
    prices = {},
    positions = [],
    systemMetrics = [],
    notifications = [],
    proposals = [],
    tradeFeed = [],
    riskAlerts = [],
    regime,
    killSwitchActive,
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
  const isInMemoryMode = String((dashboardData as Record<string, unknown> | null)?.mode ?? '').includes('in_memory')
  const baseSystemStatus = useSystemStatus()
  const systemStatus = systemFeedError ? 'error' : baseSystemStatus

  // Live P&L (realized + mark-to-market unrealized) and live-marked positions —
  // the same source the header chip uses, so the two headline numbers agree.
  const livePnl = useLivePnl()
  const livePositions = useLivePositions()
  // Real-time equity samples so an open position renders a moving curve even
  // before any trade closes (no filled orders → order-derived curve is empty).
  const liveEquitySeries = useLiveEquitySeries()
  const pricesAgeMs = pricesFreshnessMs(prices)
  const pricesLive = pricesAgeMs != null && pricesAgeMs <= PRICE_FRESHNESS_MS

  const formatTimeAgoSafe = useCallback((date: Date) => formatTimeAgo(date), [])
  const summary = useMemo(() => {
    const dailyPnlNumeric = orders.reduce((sum, order) => sum + (toFiniteNumber(order?.pnl) ?? 0), 0)
    const closedTrades = orders.filter((order) => isClosedTrade(order) && toFiniteNumber(order?.pnl) != null)
    const wins = closedTrades.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) > 0).length
    const losses = closedTrades.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) < 0).length
    // Win rate excludes scratch trades (pnl == 0) from the denominator so the UI
    // matches the backend canonical definition: winning / (winning + losing).
    const decidedTrades = wins + losses
    const winRate = decidedTrades > 0 ? (wins / decidedTrades) * 100 : null
    // Active = abs(qty) > 0, the backend canonical rule (side-agnostic), so the
    // count matches diagnose_positions / get_active_position_count. Shared with
    // the Open Positions table (below) via isActivePosition so the headline KPI
    // and the rows it summarises always agree on which positions are open.
    const activePositions = positions.filter(isActivePosition).length

    // Daily Change % = live total P&L (realized + live mark-to-market unrealized)
    // as a % of the account equity base. Using the live total — not realized-only
    // order PnL — means it moves with the market every tick and always agrees in
    // sign with the Total P&L headline, instead of the old behaviour that read
    // 0.00% while an open position was underwater. Falls back to a backend-supplied
    // value only when there is no live order/position to mark.
    const baseEquity = getMetric(systemMetrics, 'portfolio_value')
      ?? getMetric(systemMetrics, 'account_equity')
      ?? getMetric(systemMetrics, 'equity')
      ?? getMetric(systemMetrics, 'starting_equity')
      ?? DEFAULT_PAPER_EQUITY
    const liveDailyChange =
      livePnl.hasData && baseEquity > 0 ? (livePnl.total / baseEquity) * 100 : null
    const dailyChangeFromMetric = getMetric(systemMetrics, 'daily_change_pct')
    const dailyChangeFromDashboard = toFiniteNumber((dashboardData as Record<string, unknown> | null)?.['daily_change_pct'])
    const dailyChange = liveDailyChange ?? dailyChangeFromMetric ?? dailyChangeFromDashboard ?? null

    return {
      dailyPnlNumeric,
      winRate,
      activePositions,
      dailyChange,
      hasOrders: orders.length > 0,
      hasClosedTrades: closedTrades.length > 0,
    }
  }, [orders, positions, systemMetrics, dashboardData, livePnl])

  const closedTradePnls = useMemo(
    () => orders
      .filter((order) => isClosedTrade(order))
      .map((order) => toFiniteNumber(order?.pnl))
      .filter((pnl): pnl is number => pnl != null),
    [orders],
  )
  const fallbackPerformanceSummary = useMemo(() => {
    if (closedTradePnls.length === 0) return null
    const total = closedTradePnls.reduce((sum, pnl) => sum + pnl, 0)
    const wins = closedTradePnls.filter((pnl) => pnl > 0).length
    const losses = closedTradePnls.filter((pnl) => pnl < 0).length
    // Exclude scratch trades (pnl == 0) from the win-rate denominator to match
    // the backend canonical definition: winning / (winning + losing).
    const decided = wins + losses
    return {
      total_pnl: total,
      win_rate: decided > 0 ? wins / decided : 0,
      best_trade: Math.max(...closedTradePnls),
      worst_trade: Math.min(...closedTradePnls),
    }
  }, [closedTradePnls])
  const closedTradeCount = closedTradePnls.length

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
  const performanceSummarySource: PerformanceSummarySource = apiSummaryHasSignal
    ? 'api'
    : (fallbackPerformanceSummary != null ? 'local_closed_trades' : 'none')
  const tinyBestTradeExplanation = getTinyBestTradeExplanation(
    resolvedPerformanceSummary?.best_trade,
    performanceSummarySource,
    closedTradeCount,
  )
  const performanceCells = useMemo(() => buildPerformanceCells(resolvedPerformanceSummary), [resolvedPerformanceSummary])

  const realAgents = useMemo(() => {
    const grouped = agentLogs.reduce<Record<string, { displayName: string; count: number; lastSeen: Date | null }>>((acc, log) => {
      // Agent spawn/retire rows (log_type='lifecycle') are not produced output —
      // counting them made idle learning agents (IC / Reflection / Proposer)
      // read "1 event" while the Cognitive Engine correctly showed 0. Skip them
      // so the per-agent count reflects real work, consistent across all panels.
      if (isLifecycleLog(log)) return acc
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
    const incomingAgents = Object.entries(grouped).map<AgentSummary>(([, data]) => {
      const ageMs = data.lastSeen ? now - data.lastSeen.getTime() : Infinity
      const status: AgentSummary['status'] = ageMs <= AGENT_LIVE_THRESHOLD_MS ? 'Live' : 'Idle'
      const tier: AgentSummary['tier'] = status === 'Live' ? 'active' : data.count > 0 ? 'challenger' : 'inactive'
      return {
        name: data.displayName,
        eventCount: data.count,
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
      const mappedStatus: AgentSummary['status'] = ageMs <= AGENT_LIVE_THRESHOLD_MS ? 'Live' : 'Idle'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, statusDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? status.name,
        // Heartbeat is the canonical event tally (the same number the backend
        // Scorecards read from Redis). When a heartbeat exists it wins outright
        // — we never add the log-derived count on top, which is what made the
        // table and the scorecard disagree.
        eventCount: status.event_count ?? existing?.eventCount ?? 0,
        lastSeen,
        status: mergedStatus,
        tier: agentTierFromStatus(mergedStatus),
        source: existing ? 'hybrid' : 'realtime',
      })
    }

    for (const inst of agentInstances) {
      const agentKey = canonicalAgentKey(inst.pool_name)
      const existing = normalizedByName.get(agentKey)
      const startedDate = parseTimestamp(inst.started_at)
      // Lifecycle snapshots are not real-time health — they never claim "Live".
      const mappedStatus: AgentSummary['status'] = 'Idle'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, startedDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? inst.pool_name,
        // Lifecycle event_count is the LAST-resort source: use it only when no
        // heartbeat or log signal already set the count (so it never double-
        // counts an agent that is also heartbeating).
        eventCount: existing?.eventCount ?? inst.event_count ?? 0,
        lastSeen,
        status: mergedStatus,
        tier: agentTierFromStatus(mergedStatus),
        source: existing ? 'hybrid' : 'persisted',
      })
    }

    // Backfill the full documented roster so every agent in the pipeline is
    // always represented in the UI. An agent that has not reported yet reads as
    // Idle rather than silently vanishing — reporting agents above are left
    // untouched; only never-seen names get an Idle placeholder.
    for (const name of ALL_AGENT_NAMES) {
      const agentKey = canonicalAgentKey(name)
      if (!normalizedByName.has(agentKey)) {
        normalizedByName.set(agentKey, {
          name,
          eventCount: 0,
          lastSeen: null,
          status: 'Idle',
          tier: 'inactive',
          source: 'persisted',
        })
      }
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
            {([
              {
                // Realized + live mark-to-market unrealized — same source as the
                // header chip, and it moves as prices stream (no longer static).
                title: 'Total P&L',
                value: (
                  <LiveNumber
                    value={livePnl.hasData ? livePnl.total : null}
                    className={performancePnlColorClass(livePnl.hasData ? livePnl.total : null)}
                  >
                    {livePnl.hasData ? signedUSD(livePnl.total) : '--'}
                  </LiveNumber>
                ),
                sub: livePnl.hasData ? (
                  <div className="flex flex-wrap gap-x-5 gap-y-1">
                    {([
                      { label: 'Realized', amount: livePnl.realized },
                      { label: 'Unrealized', amount: livePnl.unrealized },
                    ] as const).map(({ label, amount }) => (
                      <div key={label} className="flex flex-col gap-0.5">
                        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
                          {label}
                        </span>
                        <span className={cn('font-mono tabular-nums text-xs font-semibold', performancePnlColorClass(amount))}>
                          {signedUSD(amount)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : undefined,
                badge: <LiveDot live={pricesLive} />,
                trend: 0,
              },
              {
                title: 'Win Rate',
                value: formatWinRate(summary.winRate, summary.hasClosedTrades),
                trend: 0,
              },
              {
                title: 'Active Positions',
                value: sanitizeValue(summary.activePositions),
                trend: 0,
              },
              {
                title: 'Daily Change %',
                value: formatDailyChange(summary.dailyChange),
                trend:
                  Math.abs(summary.dailyChange ?? 0) < DAILY_CHANGE_DEADBAND_PCT
                    ? 0
                    : Math.sign(summary.dailyChange ?? 0),
              },
            ] as Array<{ title: string; value: ReactNode; trend: number; sub?: ReactNode; badge?: ReactNode }>).map((item) => (
              <div key={item.title} className={cardClass}>
                <div className="mb-3 flex items-center justify-between">
                  <p className={sectionTitleClass}>{item.title}</p>
                  {item.badge ? (
                    item.badge
                  ) : item.trend > 0 ? (
                    <TrendingUp className="h-4 w-4 text-emerald-500" />
                  ) : item.trend < 0 ? (
                    <TrendingDown className="h-4 w-4 text-rose-500" />
                  ) : (
                    <span className="h-4 w-4" />
                  )}
                </div>
                <p className={valueClass}>{item.value}</p>
                {item.sub ? <div className="mt-2">{item.sub}</div> : null}
              </div>
            ))}
          </div>

          {/* The detail behind the "Active Positions" KPI above — without this
              the overview showed a count (e.g. "1") with no way to see the
              underlying position anywhere on the page. */}
          <OpenPositionsPanel />

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Performance</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {performanceCells.map((cell) => (
                <div key={cell.label} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <p className={mutedClass}>{cell.label}</p>
                  <p className={cn('mt-1 text-sm font-mono tabular-nums font-semibold', cell.colorClass)}>{cell.value}</p>
                  {cell.label === 'Best Trade' && tinyBestTradeExplanation ? (
                    <p
                      data-testid="best-trade-tiny-explanation"
                      className="mt-1 text-xs text-slate-500 dark:text-slate-400"
                    >
                      {tinyBestTradeExplanation}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Equity Curve</p>
              </div>
              <EquityCurve orders={orders} liveSeries={liveEquitySeries} />
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
                        agentCardBorderClass(agent.status),
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-sans font-semibold text-slate-900 dark:text-slate-100">{agentDisplayName(agent.name)}</p>
                        <div className="flex items-center gap-1.5">
                          <span className={cn('h-2 w-2 rounded-full', agentCardDotClass(agent.status))} />
                          <span className={cn('text-xs font-mono font-semibold', agentCardTextClass(agent.status))}>{agent.status}</span>
                        </div>
                      </div>
                      <div className="mt-2 flex items-center justify-between">
                        {agent.eventCount > 0 ? (
                          <p className="text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                            {agent.eventCount} events
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
              <PriceFreshnessStatus prices={prices} loading={pricesLoading} />
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
                        <p className={cn('text-xs font-mono tabular-nums', priceChangeTextClass(change, hasData))}>
                          {priceChangeText(change, hasData)}
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
        <AgentsDashboard
          realAgents={realAgents}
          wiringFreshness={wiringFreshness}
          agentStatuses={agentStatuses}
          agentInstances={agentInstances}
          agentLogs={agentLogs}
          notifications={notifications}
          proposals={proposals}
          decisionStats={decisionStats}
          recentDecisions={recentDecisions}
          recentEvents={recentEvents}
          apiHealth={apiHealth}
          marketTickCount={marketTickCount}
          lastMarketSymbol={lastMarketSymbol}
          streamStats={streamStats}
          wsConnected={wsConnected}
          isInMemoryMode={isInMemoryMode}
        />
      )}

      {section === 'learning' && <LearningConsole setActiveTraceId={setActiveTraceId} />}

      {section === 'proposals' && <ProposalsSection />}

      {section === 'system' && (
        <SystemDashboard
          wsConnected={wsConnected}
          wsMessageCount={wsMessageCount}
          wsLastMessageTimestamp={wsLastMessageTimestamp}
          wsDiagnostics={wsDiagnostics}
          streamStats={streamStats}
          recentEvents={recentEvents}
          agentStatuses={agentStatuses}
          prices={prices}
          positions={livePositions}
          tradeFeed={tradeFeed}
          orders={orders}
          agentLogs={agentLogs}
          notifications={notifications}
          proposals={proposals}
          riskAlerts={riskAlerts}
          pricesFetched={pricesFetched}
          isInMemoryMode={isInMemoryMode}
          resolvedPerformanceSummary={resolvedPerformanceSummary}
          apiHealth={apiHealth}
          systemFeedError={systemFeedError}
          llmAvailable={llmAvailable}
          llmProvider={llmProvider}
          persistedCounts={persistedCounts}
          persistedEvents={persistedEvents}
          persistedLogs={persistedLogs}
          regime={regime}
          killSwitchActive={killSwitchActive}
          setActiveTraceId={setActiveTraceId}
        />
      )}
    </>
  )

  // Every section is a dense ops console of side-by-side cards, so they all use
  // the full screen width. Keeping one width across pages stops the overview (and
  // other pages) from looking like a cramped, disconnected column next to the
  // wider ones.
  const mainMaxWidthClass = 'max-w-screen-2xl'

  return (
    <div className="min-h-screen bg-slate-100 pb-20 text-slate-900 dark:bg-slate-950 dark:text-slate-100 lg:pb-4">
      <main className={cn('mx-auto space-y-3 px-3 py-4 sm:px-4', mainMaxWidthClass)}>
        <SectionHeader section={section} />
        <div
          className={cn(
            'rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-widest',
            systemStatusBadgeClass(systemStatus),
          )}
        >
          System Status: {systemStatus}
        </div>
        {/* Reasoning-LLM degraded/down — page-level indicator (fail-closed warning) */}
        <LLMDegradedBanner />
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
