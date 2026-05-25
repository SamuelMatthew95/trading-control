'use client'

import { useMemo } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { cn } from '@/lib/utils'
import { deriveActivityIndicator, ACTIVITY_FRESH_MS } from '@/lib/agent-activity'
import { formatUSD, formatTimeAgo, toFiniteNum as toNum } from '@/lib/formatters'
import { GRADE_STYLES } from '@/lib/grade-colors'
import { Activity, BarChart2, Layers, TrendingDown, TrendingUp } from 'lucide-react'

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

function tradeFeedEmptyLabel(reason: string | null): string {
  if (reason === 'db_degraded') return 'DB unavailable — fills will appear when DB reconnects'
  if (reason === 'no_orders_executed') return 'No orders executed yet — decisions are being evaluated'
  if (reason === 'lifecycle_not_persisted') return 'Orders placed but lifecycle rows are pending'
  if (reason === 'no_executable_intents') return 'Pipeline active — no executable intents yet'
  return 'No fills yet — waiting for executed trades'
}

function activityDotClass(indicator: string): string {
  if (indicator === 'live') return 'animate-pulse bg-emerald-500'
  if (indicator === 'waiting') return 'bg-amber-400'
  return 'bg-slate-400'
}

function activityLabel(indicator: string): string {
  if (indicator === 'live') return 'LIVE'
  if (indicator === 'waiting') return 'WAITING'
  return 'OFFLINE'
}

function confColorClass(conf: number | null): string {
  if (conf == null) return 'text-slate-400'
  if (conf > 0.8) return 'text-emerald-500'
  if (conf >= 0.5) return 'text-amber-500'
  return 'text-slate-400'
}

function actionBadgeClass(action: string): string {
  if (action === 'BUY') return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
  if (action === 'SELL') return 'bg-rose-500/15 text-rose-500'
  return 'bg-slate-500/10 text-slate-500'
}

function positionSideBadgeClass(side: string): string {
  if (side === 'LONG') return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
  if (side === 'SHORT') return 'bg-rose-500/15 text-rose-500'
  return 'bg-slate-500/10 text-slate-500'
}

function winRateFromFeed(feed: { pnl?: number | null }[]): number | null {
  const withPnl = feed.filter((t) => t.pnl != null)
  if (withPnl.length === 0) return null
  return (withPnl.filter((t) => (t.pnl ?? 0) > 0).length / withPnl.length) * 100
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
      ? 'text-emerald-500'
      : sign === 'negative'
        ? 'text-rose-500'
        : 'text-slate-900 dark:text-slate-100'

  return (
    <div className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          {label}
        </p>
        {Icon && <Icon className="h-3.5 w-3.5 text-slate-400 dark:text-slate-600" />}
      </div>
      <p className={cn('font-black font-mono tabular-nums text-xl leading-none', valueColor)}>{value}</p>
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
  const { tradeFeed = [] } = useCodexStore()

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
                  isBuy ? 'border-l-emerald-500' : 'border-l-rose-500',
                )}
              >
                {/* Direction badge */}
                <span
                  className={cn(
                    'shrink-0 rounded-md px-2 py-1 text-[11px] font-black tracking-wide',
                    isBuy
                      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                      : 'bg-rose-500/15 text-rose-500',
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
                      <span className="text-xs text-slate-500 dark:text-slate-400">{qty} units</span>
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
                    <p className={cn('font-black font-mono tabular-nums text-sm', pnlPos ? 'text-emerald-500' : 'text-rose-500')}>
                      {pnlPos ? '+' : '-'}{formatUSD(pnl)}
                    </p>
                    {pnlPct != null && (
                      <p className={cn('text-[11px] font-mono tabular-nums', pnlPos ? 'text-emerald-400' : 'text-rose-400')}>
                        {pnlPos ? '+' : ''}{pnlPct.toFixed(1)}%
                      </p>
                    )}
                  </div>
                )}

                {/* Grade */}
                {gradeStyle && grade && (
                  <span className={cn('shrink-0 rounded-md px-2 py-1 text-xs font-black', gradeStyle.badge)}>
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
// Agent Activity
// ---------------------------------------------------------------------------

function AgentActivityPanel({ setActiveTraceId }: { setActiveTraceId: (id: string) => void }) {
  const { agentLogs = [], wsConnected = false } = useCodexStore()

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
            const rawConf = toNum((log as Record<string, unknown>)?.confidence_score ?? log?.confidence)
            // Normalise to 0-1 fraction: values > 1 are percentages from the reasoning agent.
            const conf = rawConf == null ? null : rawConf > 1 ? rawConf / 100 : rawConf
            const confPct = conf == null ? null : Math.round(conf * 100)
            const confColor = confColorClass(conf)

            const rawName = String(log?.agent_name || log?.agent || (log as Record<string, unknown>)?.source || '')
            const displayName = rawName
              ? rawName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
              : 'Agent'
            const symbol = String(
              log?.symbol || ((log as Record<string, unknown>)?.data as Record<string, unknown>)?.symbol || '',
            )
            const action = String(log?.action || (log as Record<string, unknown>)?.decision || '').toUpperCase()
            const msg = resolveMessage(
              log?.message || (log as Record<string, unknown>)?.summary || (log as Record<string, unknown>)?.primary_edge,
            )
            const ts = String(log?.timestamp || (log as Record<string, unknown>)?.created_at || '')

            return (
              <div key={String(log?.id || `${rawName}-${idx}`)} className="px-5 py-3">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">{displayName}</span>
                    {symbol && (
                      <span className="font-mono text-[11px] text-slate-400">{symbol}</span>
                    )}
                    {action && action !== '' && (
                      <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-black tracking-wide', actionBadgeClass(action))}>
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
// Open Positions
// ---------------------------------------------------------------------------

function OpenPositionsPanel() {
  const { positions = [] } = useCodexStore()

  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Open Positions
        </p>
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {positions.length} active
        </span>
      </div>

      {positions.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-12">
          <Layers className="h-9 w-9 text-slate-300 dark:text-slate-700" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No open positions</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                {['Symbol', 'Side', 'Qty', 'Entry', 'Current', 'P&L', 'P&L %'].map((h, i) => (
                  <th
                    key={h}
                    className={cn(
                      'py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400',
                      i === 0 ? 'pl-5 pr-4 text-left' : i >= 4 ? 'px-4 text-right last:pr-5' : 'px-4 text-left',
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {positions.map((pos, i) => {
                const pnl = toNum((pos as Record<string, unknown>)?.pnl)
                const pnlPct = toNum((pos as Record<string, unknown>)?.pnl_percent)
                const isPos = (pnl ?? 0) >= 0
                const side = String((pos as Record<string, unknown>)?.side ?? '').toUpperCase()
                const symbol = String((pos as Record<string, unknown>)?.symbol ?? '--')
                // ORM uses `quantity`; paper-broker Redis state uses `qty` — try both.
                const qty = toNum((pos as Record<string, unknown>)?.quantity) ?? toNum((pos as Record<string, unknown>)?.qty)
                const entryPrice = toNum((pos as Record<string, unknown>)?.entry_price)
                const currentPrice = toNum((pos as Record<string, unknown>)?.current_price)

                return (
                  <tr
                    key={`${symbol}-${i}`}
                    className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <td className="py-3 pl-5 pr-4 font-mono font-bold text-slate-900 dark:text-slate-100">
                      {symbol}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('rounded-md px-2 py-0.5 text-[11px] font-black', positionSideBadgeClass(side))}>
                        {side || '--'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {qty != null ? qty : '--'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {entryPrice != null ? formatUSD(entryPrice) : '--'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {currentPrice != null ? formatUSD(currentPrice) : '--'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {pnl != null ? (
                        <span
                          className={cn(
                            'font-black font-mono tabular-nums',
                            isPos ? 'text-emerald-500' : 'text-rose-500',
                          )}
                        >
                          {isPos ? '+' : '-'}{formatUSD(pnl)}
                        </span>
                      ) : (
                        <span className="text-slate-400">--</span>
                      )}
                    </td>
                    <td className="py-3 pl-4 pr-5 text-right">
                      {pnlPct != null ? (
                        <span
                          className={cn(
                            'font-mono tabular-nums text-xs',
                            isPos ? 'text-emerald-500' : 'text-rose-500',
                          )}
                        >
                          {isPos ? '+' : ''}{pnlPct.toFixed(2)}%
                        </span>
                      ) : (
                        <span className="text-slate-400 text-xs">--</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
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
    positions = [],
    performanceSummary = null,
  } = useCodexStore()

  const stats = useMemo(() => {
    const totalPnl =
      performanceSummary?.total_pnl != null && performanceSummary.total_pnl !== 0
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

    return { totalPnl, winRatePct, totalTrades, wins, fills: tradeFeed.length, activePositions: positions.length }
  }, [tradeFeed, positions, performanceSummary])

  const pnlSign =
    stats.totalPnl > 0.005 ? 'positive' : stats.totalPnl < -0.005 ? 'negative' : 'neutral'

  const winRateSign =
    stats.winRatePct == null ? 'neutral' : stats.winRatePct >= 50 ? 'positive' : 'negative'

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          label="Session P&L"
          value={stats.totalPnl < -0.005 ? `(${formatUSD(stats.totalPnl)})` : formatUSD(stats.totalPnl)}
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

      {/* Open positions — full width */}
      <OpenPositionsPanel />
    </div>
  )
}
