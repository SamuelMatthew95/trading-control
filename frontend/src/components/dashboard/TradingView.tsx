'use client'

import { useMemo } from 'react'
import { useDashboardStore } from '@/stores/useDashboardStore'
import { cn } from '@/lib/utils'
import { deriveActivityIndicator, ACTIVITY_FRESH_MS } from '@/lib/agent-activity'
import { formatUSD, formatQuantity, formatTimeAgo, getField, getStr, isActivePosition, toFiniteNum as toNum } from '@/lib/formatters'
import { GRADE_STYLES } from '@/lib/grade-colors'
import { Activity, BarChart2, History, TrendingDown, TrendingUp } from 'lucide-react'
import { useLivePnl } from '@/hooks/useLivePnl'
import { useLivePositions } from '@/hooks/useLivePositions'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState } from '@/components/ui/empty-state'
import {
  tradeFeedEmptyLabel,
  activityDotClass,
  activityLabel,
  confColorClass,
  actionBadgeClass,
  pnlColorClass,
  winRateFromFeed,
} from '@/lib/dashboard-helpers'

// Modes the ReasoningAgent emits when the LLM is unavailable and it falls back
// to a rule-based decision. The prefix "fallback:" is set by the agent itself.
const FALLBACK_LABELS: Record<string, string> = {
  skip_reasoning: 'Rule-based fallback decision',
  reject_signal: 'Signal rejected (rule-based)',
  use_last_reflection: 'Reused last reflection',
}

const resolveMessage = (raw: unknown): string => {
  const text = String(raw ?? '').trim()
  if (!text || text === 'undefined' || text === '--') return ''
  if (text.startsWith('fallback:')) {
    const mode = text.slice('fallback:'.length)
    return FALLBACK_LABELS[mode] ?? 'Rule-based fallback (LLM unavailable)'
  }
  return text
}


// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

function StatTile({
  label,
  value,
  sub,
  sign,
  icon: Icon,
}: {
  label: string
  value: string
  sub?: string
  sign?: 'positive' | 'negative' | 'neutral'
  icon?: React.ComponentType<{ className?: string }>
}) {
  const valueColor =
    sign === 'positive'
      ? 'text-success'
      : sign === 'negative'
        ? 'text-danger'
        : 'text-slate-900 dark:text-slate-100'

  return (
    <div className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          {label}
        </p>
        {Icon && <Icon className="h-3.5 w-3.5 text-slate-400 dark:text-slate-600" />}
      </div>
      <p className={cn('font-semibold font-mono tabular-nums text-xl leading-none', valueColor)}>{value}</p>
      {sub && <p className="text-[10px] font-mono text-slate-400 dark:text-slate-600">{sub}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Trade Feed
// ---------------------------------------------------------------------------

function TradeFeedPanel({
  emptyReason,
  upstream,
  setActiveTraceId,
}: {
  emptyReason: string | null
  upstream: { signal_events?: number; decisions_evaluated?: number; ee_last_status?: string | null } | null
  setActiveTraceId: (id: string) => void
}) {
  const { tradeFeed = [] } = useDashboardStore()

  const emptyLabel = tradeFeedEmptyLabel(emptyReason)

  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Trade Feed
        </p>
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {tradeFeed.length} fills
        </span>
      </div>

      {tradeFeed.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 px-6 text-center">
          <BarChart2 className="h-9 w-9 text-slate-300 dark:text-slate-700" />
          <p className="text-sm text-slate-500 dark:text-slate-400">{emptyLabel}</p>
          {upstream && (upstream.signal_events ?? 0) > 0 && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs font-mono text-slate-500 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-400 space-y-1">
              <p>Signals: {upstream.signal_events?.toLocaleString() ?? 0} · Decisions: {upstream.decisions_evaluated?.toLocaleString() ?? 0}</p>
              {upstream.ee_last_status && (
                <p className="text-slate-400 dark:text-slate-500">EE: {upstream.ee_last_status}</p>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="max-h-[480px] divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800/60">
          {tradeFeed.slice(0, 50).map((trade) => {
            const isBuy = trade.side === 'buy'
            const pnl = toNum(trade.pnl)
            const pnlPct = toNum(trade.pnl_percent)
            const pnlPos = (pnl ?? 0) >= 0
            const exitPrice = toNum(trade.exit_price)
            const entryPrice = toNum(trade.entry_price)
            const qty = toNum(trade.qty)
            const grade = trade.grade
            const gradeStyle = grade ? (GRADE_STYLES[grade] ?? GRADE_STYLES.C) : null

            return (
              <div
                key={trade.id}
                className={cn(
                  'group flex items-center gap-3 px-5 py-3 transition-colors',
                  'hover:bg-slate-50 dark:hover:bg-slate-800/40',
                  'border-l-[3px]',
                  isBuy ? 'border-l-success' : 'border-l-danger',
                )}
              >
                {/* Direction badge */}
                <span
                  className={cn(
                    'shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold tracking-wide',
                    isBuy
                      ? 'bg-success/15 text-success'
                      : 'bg-danger/15 text-danger',
                  )}
                >
                  {isBuy ? 'BUY' : 'SELL'}
                </span>

                {/* Symbol + price path */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm text-slate-900 dark:text-slate-100">
                      {trade.symbol}
                    </span>
                    {qty != null && (
                      <span className="text-xs text-slate-500 dark:text-slate-400">{formatQuantity(qty)} units</span>
                    )}
                  </div>
                  {entryPrice != null && exitPrice != null ? (
                    <p className="mt-0.5 flex items-center gap-1 text-[11px] font-mono text-slate-400">
                      <span>{formatUSD(entryPrice)}</span>
                      <span>→</span>
                      <span>{formatUSD(exitPrice)}</span>
                    </p>
                  ) : exitPrice != null ? (
                    <p className="mt-0.5 text-[11px] font-mono text-slate-400">@ {formatUSD(exitPrice)}</p>
                  ) : null}
                </div>

                {/* P&L */}
                {pnl != null && (
                  <div className="shrink-0 text-right">
                    <p className={cn('font-semibold font-mono tabular-nums text-sm', pnlPos ? 'text-success' : 'text-danger')}>
                      {pnlPos ? '+' : '-'}{formatUSD(pnl)}
                    </p>
                    {pnlPct != null && (
                      <p className={cn('text-[11px] font-mono tabular-nums', pnlPos ? 'text-success' : 'text-danger')}>
                        {pnlPos ? '+' : ''}{pnlPct.toFixed(1)}%
                      </p>
                    )}
                  </div>
                )}

                {/* Grade */}
                {gradeStyle && grade && (
                  <span className={cn('shrink-0 rounded-md px-2 py-1 text-xs font-semibold', gradeStyle.badge)}>
                    {grade}
                  </span>
                )}

                {/* Time + trace */}
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-[10px] font-mono text-slate-400 dark:text-slate-600">
                    {formatTimeAgo(trade.filled_at ?? trade.created_at)}
                  </span>
                  {trade.execution_trace_id && (
                    <button
                      onClick={() => setActiveTraceId(trade.execution_trace_id!)}
                      className="text-[10px] font-mono text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:text-slate-600 dark:hover:text-slate-300"
                    >
                      trace:{trade.execution_trace_id.slice(0, 8)}…
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Closed Trades — the verifiable ledger behind the headline P&L
// ---------------------------------------------------------------------------

/**
 * Compact table of completed round-trips (newest first, from
 * `/dashboard/state.closed_trades`). Sits below Open Positions / the trade feed
 * so the operator can reconcile the header P&L against actual past trades.
 */
function ClosedTradesPanel() {
  const { closedTrades = [] } = useDashboardStore()

  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Closed Trades
        </p>
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {closedTrades.length} closed
        </span>
      </div>

      {closedTrades.length === 0 ? (
        <div className="px-4 py-4">
          <EmptyState icon={History} message="No closed trades yet this session" />
        </div>
      ) : (
        <div className="max-h-[360px] overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-5">Time</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Entry → Exit</TableHead>
                <TableHead className="pr-5 text-right">P&L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {closedTrades.slice(0, 50).map((trade, i) => (
                <TableRow key={`${trade.symbol}-${trade.closed_at ?? i}`}>
                  <TableCell
                    className="whitespace-nowrap pl-5 font-mono text-xs tabular-nums text-slate-500 dark:text-slate-400"
                    title={trade.closed_at ?? undefined}
                  >
                    {formatTimeAgo(trade.closed_at) || '--'}
                  </TableCell>
                  <TableCell className="font-mono font-semibold">{trade.symbol || '--'}</TableCell>
                  <TableCell>
                    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide', actionBadgeClass(trade.side.toUpperCase()))}>
                      {trade.side}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums text-slate-700 dark:text-slate-300">
                    {formatQuantity(trade.qty)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right font-mono text-xs tabular-nums text-slate-700 dark:text-slate-300">
                    {trade.entry_price != null ? formatUSD(trade.entry_price) : '--'}
                    <span className="text-slate-400 dark:text-slate-500"> → </span>
                    {trade.exit_price != null ? formatUSD(trade.exit_price) : '--'}
                  </TableCell>
                  <TableCell className="whitespace-nowrap pr-5 text-right">
                    {trade.pnl != null ? (
                      <span className={cn('font-mono text-sm font-semibold tabular-nums', pnlColorClass(trade.pnl))}>
                        {trade.pnl >= 0 ? '+' : '-'}{formatUSD(trade.pnl)}
                        {trade.pnl_percent != null && (
                          <span className="ml-1.5 text-xs font-normal">
                            {trade.pnl_percent >= 0 ? '+' : ''}{trade.pnl_percent.toFixed(2)}%
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">--</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Agent Activity
// ---------------------------------------------------------------------------

function AgentActivityPanel({ setActiveTraceId }: { setActiveTraceId: (id: string) => void }) {
  const { agentLogs = [], wsConnected = false } = useDashboardStore()

  const logs = useMemo(() => agentLogs.slice(0, 25), [agentLogs])

  // Use agentLogs[0] (newest entry — store prepends) for freshness, not logs[0]
  // which is the oldest of the display window when agentLogs has >25 entries.
  const activityIndicator = useMemo(
    () => deriveActivityIndicator(agentLogs[0]?.timestamp, wsConnected, ACTIVITY_FRESH_MS),
    [agentLogs, wsConnected],
  )

  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Agent Activity
        </p>
        <div className="flex items-center gap-2">
          <span className={cn('h-2 w-2 rounded-full', activityDotClass(activityIndicator))} />
          <span className="text-xs font-mono text-slate-500 dark:text-slate-400">
            {activityLabel(activityIndicator)}
          </span>
        </div>
      </div>

      {logs.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-12">
          <Activity className="h-9 w-9 text-slate-300 dark:text-slate-700" />
          <p className="text-sm text-slate-500 dark:text-slate-400">Waiting for agent activity</p>
        </div>
      ) : (
        <div className="relative max-h-[480px] divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800/60">
          {logs.map((log, idx) => {
            // ReasoningAgent emits confidence_score (0-100); SignalGenerator emits confidence (0-1).
            const rawConf = toNum(getField(log, 'confidence_score') ?? log?.confidence)
            // Normalise to 0-1 fraction: values > 1 are percentages from the reasoning agent.
            const conf = rawConf == null ? null : rawConf > 1 ? rawConf / 100 : rawConf
            const confPct = conf == null ? null : Math.round(conf * 100)
            const confColor = confColorClass(conf)

            const rawName = getStr(log, 'agent_name', 'agent', 'source')
            const displayName = rawName
              ? rawName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
              : 'Agent'
            // symbol may sit on the log or nested under log.data (signal payloads).
            const symbol = getStr(log, 'symbol') || getStr(getField(log, 'data'), 'symbol')
            const action = getStr(log, 'action', 'decision').toUpperCase()
            const msg = resolveMessage(
              log?.message ?? getField(log, 'summary') ?? getField(log, 'primary_edge'),
            )
            const ts = getStr(log, 'timestamp', 'created_at')

            return (
              <div key={String(log?.id || `${rawName}-${idx}`)} className="px-5 py-3">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">{displayName}</span>
                    {symbol && (
                      <span className="font-mono text-[11px] text-slate-400">{symbol}</span>
                    )}
                    {action && action !== '' && (
                      <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide', actionBadgeClass(action))}>
                        {action}
                      </span>
                    )}
                    {confPct != null && (
                      <span className={cn('font-mono text-[10px] font-semibold', confColor)}>
                        {confPct}%
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {typeof log?.trace_id === 'string' && log.trace_id ? (
                      <button
                        onClick={() => setActiveTraceId(log.trace_id as string)}
                        className="font-mono text-[10px] text-slate-400 transition-colors hover:text-slate-600 dark:hover:text-slate-300"
                      >
                        {(log.trace_id as string).slice(0, 8)}…
                      </button>
                    ) : null}
                    <span className="font-mono text-[10px] text-slate-400 dark:text-slate-600">
                      {formatTimeAgo(ts)}
                    </span>
                  </div>
                </div>
                {msg && (
                  <p className="text-xs leading-snug text-slate-600 dark:text-slate-400">{msg}</p>
                )}
              </div>
            )
          })}
          <div className="pointer-events-none sticky bottom-0 h-8 bg-gradient-to-t from-white to-transparent dark:from-slate-900" />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main TradingView
// ---------------------------------------------------------------------------

export interface TradingViewProps {
  setActiveTraceId: (id: string) => void
  tradeFeedEmptyReason?: string | null
  tradeFeedUpstream?: {
    signal_events?: number
    decisions_evaluated?: number
    ee_last_status?: string | null
  } | null
}

export function TradingView({
  setActiveTraceId,
  tradeFeedEmptyReason = null,
  tradeFeedUpstream = null,
}: TradingViewProps) {
  const {
    tradeFeed = [],
    performanceSummary = null,
    pnlSummary = null,
  } = useDashboardStore()

  // Realized + live mark-to-market unrealized, re-valued against the price
  // stream every tick — the SAME canonical source as the header chip and the
  // Overview headline, so the three can never show three different P&L numbers.
  const livePnl = useLivePnl()
  const livePositions = useLivePositions()

  const stats = useMemo(() => {
    // Session P&L marks open positions to the live price stream every tick, so it
    // never freezes between the 30s REST /pnl snapshots. Fall back to the broker
    // snapshot, then the DB/trends aggregate, then the realized trade-feed sum
    // only when there is no live order/position to mark.
    const totalPnl =
      livePnl.hasData
        ? livePnl.total
        : pnlSummary?.total_pnl != null
          ? pnlSummary.total_pnl
          : performanceSummary?.total_pnl != null && performanceSummary.total_pnl !== 0
            ? performanceSummary.total_pnl
            : tradeFeed.reduce((sum, t) => sum + (toNum(t.pnl) ?? 0), 0)

    const totalTrades = performanceSummary?.total_trades ?? tradeFeed.filter((t) => t.pnl != null).length
    // Derive wins from summary when available so sub-text matches the aggregate win rate.
    // tradeFeed is a bounded cache; it undershoots when total_trades > cache size.
    const wins =
      performanceSummary?.win_rate != null && (performanceSummary?.total_trades ?? 0) > 0
        ? Math.round(performanceSummary.win_rate * performanceSummary.total_trades)
        : tradeFeed.filter((t) => (t.pnl ?? 0) > 0).length

    const winRatePct =
      performanceSummary?.win_rate != null && (performanceSummary?.total_trades ?? 0) > 0
        ? performanceSummary.win_rate * 100
        : winRateFromFeed(tradeFeed)

    // Active = abs(qty) > 0 (backend canonical rule), not the raw array length,
    // so a flat (qty 0) row never inflates the count. `isActivePosition` reads
    // ORM `quantity` and paper-broker `qty`, matching the Open Positions table.
    // Live-marked positions keep the count consistent with the same source.
    const activePositions = livePositions.filter(isActivePosition).length
    return {
      totalPnl,
      winRatePct,
      totalTrades,
      wins,
      fills: tradeFeed.length,
      activePositions,
      realized: livePnl.realized,
      unrealized: livePnl.unrealized,
      hasLivePnl: livePnl.hasData,
    }
  }, [tradeFeed, livePositions, performanceSummary, pnlSummary, livePnl])

  const pnlSign =
    stats.totalPnl > 0.005 ? 'positive' : stats.totalPnl < -0.005 ? 'negative' : 'neutral'

  const winRateSign =
    stats.winRatePct == null ? 'neutral' : stats.winRatePct >= 50 ? 'positive' : 'negative'

  // Spell out the realized/unrealized split so "Session P&L" (which folds in
  // open-position mark-to-market) reads unambiguously. Prefer the live
  // breakdown (moves with the market every tick); fall back to the broker
  // snapshot only when there is no live order/position to mark.
  const pnlSub =
    stats.hasLivePnl
      ? `${formatUSD(stats.realized)} realized · ${formatUSD(stats.unrealized)} unrealized`
      : pnlSummary != null
        ? `${formatUSD(pnlSummary.realized_pnl)} realized · ${formatUSD(pnlSummary.unrealized_pnl)} unrealized`
        : undefined

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label="Session P&L"
          value={stats.totalPnl < -0.005 ? `(${formatUSD(stats.totalPnl)})` : formatUSD(stats.totalPnl)}
          sub={pnlSub}
          sign={pnlSign}
          icon={stats.totalPnl >= 0 ? TrendingUp : TrendingDown}
        />
        <StatTile
          label="Win Rate"
          value={stats.winRatePct != null ? `${stats.winRatePct.toFixed(1)}%` : '--'}
          sub={stats.totalTrades > 0 ? `${stats.wins} of ${stats.totalTrades} closed` : 'no closed trades'}
          sign={winRateSign}
        />
        <StatTile
          label="Total Fills"
          value={String(stats.fills)}
          sub="completed"
        />
        <StatTile
          label="Open Positions"
          value={String(stats.activePositions)}
          sub={stats.activePositions === 1 ? 'position' : 'positions'}
        />
      </div>

      {/* Feed + Activity grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <TradeFeedPanel
            emptyReason={tradeFeedEmptyReason}
            upstream={tradeFeedUpstream}
            setActiveTraceId={setActiveTraceId}
          />
        </div>
        <div className="lg:col-span-2">
          <AgentActivityPanel setActiveTraceId={setActiveTraceId} />
        </div>
      </div>

      {/* Past round-trips — lets the operator verify the headline P&L number. */}
      <ClosedTradesPanel />
    </div>
  )
}
