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
import { StatTile } from '@/components/ui/stat-tile'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { SIDE_BUY } from '@/constants/trading'
import { SENTIMENT_TEXT, type Sentiment } from '@/lib/design/sentiment'
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
  skip_reasoning: UI_COPY.tradingView.fallbackSkipReasoning,
  reject_signal: UI_COPY.tradingView.fallbackRejectSignal,
  use_last_reflection: UI_COPY.tradingView.fallbackUseLastReflection,
}

const resolveMessage = (raw: unknown): string => {
  const text = String(raw ?? '').trim()
  if (!text || text === 'undefined' || text === '--') return ''
  if (text.startsWith('fallback:')) {
    const mode = text.slice('fallback:'.length)
    return FALLBACK_LABELS[mode] ?? UI_COPY.tradingView.fallbackDefault
  }
  return text
}


// ---------------------------------------------------------------------------
// Stat tile — thin adapter over the shared StatTile (sentiment-toned value)
// ---------------------------------------------------------------------------

function TradeStat({
  label,
  value,
  sub,
  sign = 'neutral',
  icon: Icon,
}: {
  label: string
  value: string
  sub?: string
  sign?: Sentiment
  icon?: React.ComponentType<{ className?: string }>
}) {
  return (
    <StatTile
      label={label}
      value={value}
      icon={Icon ? <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" aria-hidden /> : undefined}
      valueClassName={cn(
        'mt-1 text-xl leading-none',
        sign === 'neutral' ? 'text-foreground' : SENTIMENT_TEXT[sign],
      )}
      lines={sub ? [sub] : []}
      className="px-4 py-3 sm:p-3"
    />
  )
}

const feedPanelClass = 'flex flex-col overflow-hidden rounded-xl border bg-card dark:bg-popover'
const feedHeaderClass = 'flex items-center justify-between border-b px-5 py-3.5'
const feedTitleClass = 'text-xs font-semibold uppercase tracking-caps text-muted-foreground'
const feedCountClass = 'rounded-full bg-muted px-2.5 py-0.5 font-mono text-xs text-muted-foreground'

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
    <div className={feedPanelClass}>
      {/* Header */}
      <div className={feedHeaderClass}>
        <p className={feedTitleClass}>{UI_COPY.panels.tradeFeed}</p>
        <span className={feedCountClass}>
          {tradeFeed.length} {UI_COPY.tradingView.fills}
        </span>
      </div>

      {tradeFeed.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 px-6 text-center">
          <BarChart2 className="h-9 w-9 text-muted-foreground/40" aria-hidden />
          <p className="text-sm text-muted-foreground">{emptyLabel}</p>
          {upstream && (upstream.signal_events ?? 0) > 0 && (
            <div className="space-y-1 rounded-lg border bg-muted/40 px-4 py-2.5 font-mono text-xs text-muted-foreground">
              <p>
                {UI_COPY.tradingView.signals} {upstream.signal_events?.toLocaleString() ?? 0} ·{' '}
                {UI_COPY.tradingView.decisions} {upstream.decisions_evaluated?.toLocaleString() ?? 0}
              </p>
              {upstream.ee_last_status && (
                <p className="text-muted-foreground/70">{UI_COPY.tradingView.eePrefix} {upstream.ee_last_status}</p>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="max-h-[480px] divide-y overflow-y-auto">
          {tradeFeed.slice(0, 50).map((trade) => {
            const isBuy = trade.side === SIDE_BUY
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
                  'hover:bg-muted/40',
                  'border-l-[3px]',
                  isBuy ? 'border-l-success' : 'border-l-danger',
                )}
              >
                {/* Direction badge */}
                <span
                  className={cn(
                    'shrink-0 rounded-md px-2 py-1 text-2xs font-semibold tracking-caps',
                    actionBadgeClass(isBuy ? 'BUY' : 'SELL'),
                  )}
                >
                  {isBuy ? 'BUY' : 'SELL'}
                </span>

                {/* Symbol + price path */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-bold text-foreground">
                      {trade.symbol}
                    </span>
                    {qty != null && (
                      <span className="text-xs text-muted-foreground">
                        {formatQuantity(qty)} {UI_COPY.tradingView.units}
                      </span>
                    )}
                  </div>
                  {entryPrice != null && exitPrice != null ? (
                    <p className="mt-0.5 flex items-center gap-1 font-mono text-2xs text-muted-foreground/70">
                      <span>{formatUSD(entryPrice)}</span>
                      <span>→</span>
                      <span>{formatUSD(exitPrice)}</span>
                    </p>
                  ) : exitPrice != null ? (
                    <p className="mt-0.5 font-mono text-2xs text-muted-foreground/70">@ {formatUSD(exitPrice)}</p>
                  ) : null}
                </div>

                {/* P&L */}
                {pnl != null && (
                  <div className="shrink-0 text-right">
                    <p className={cn('font-mono text-sm font-semibold tabular-nums', pnlColorClass(pnl))}>
                      {pnlPos ? '+' : '-'}{formatUSD(pnl)}
                    </p>
                    {pnlPct != null && (
                      <p className={cn('font-mono text-2xs tabular-nums', pnlColorClass(pnl))}>
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
                  <span className="font-mono text-3xs text-muted-foreground/70">
                    {formatTimeAgo(trade.filled_at ?? trade.created_at)}
                  </span>
                  {trade.execution_trace_id && (
                    <button
                      type="button"
                      onClick={() => setActiveTraceId(trade.execution_trace_id!)}
                      className="font-mono text-3xs text-muted-foreground/70 opacity-0 transition-opacity hover:text-foreground/70 focus-visible:opacity-100 group-hover:opacity-100"
                    >
                      {UI_COPY.tradingView.tracePrefix}{trade.execution_trace_id.slice(0, 8)}…
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
    <div className={feedPanelClass}>
      <div className={feedHeaderClass}>
        <p className={feedTitleClass}>{UI_COPY.tradingView.closedTrades}</p>
        <span className={feedCountClass}>
          {closedTrades.length} {UI_COPY.tradingView.closed}
        </span>
      </div>

      {closedTrades.length === 0 ? (
        <div className="px-4 py-4">
          <EmptyState icon={History} message={UI_COPY.empty.closedTrades} />
        </div>
      ) : (
        <div className="max-h-[360px] overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-5">{UI_COPY.tables.time}</TableHead>
                <TableHead>{UI_COPY.tables.symbol}</TableHead>
                <TableHead>{UI_COPY.tables.side}</TableHead>
                <TableHead className="text-right">{UI_COPY.tables.qty}</TableHead>
                <TableHead className="text-right">{UI_COPY.tables.entryExit}</TableHead>
                <TableHead className="pr-5 text-right">{UI_COPY.tables.pnl}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {closedTrades.slice(0, 50).map((trade, i) => (
                <TableRow key={`${trade.symbol}-${trade.closed_at ?? i}`}>
                  <TableCell
                    className="whitespace-nowrap pl-5 font-mono text-xs tabular-nums text-muted-foreground"
                    title={trade.closed_at ?? undefined}
                  >
                    {formatTimeAgo(trade.closed_at) || NO_DATA}
                  </TableCell>
                  <TableCell className="font-mono font-semibold">{trade.symbol || NO_DATA}</TableCell>
                  <TableCell>
                    <span className={cn('rounded px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-caps', actionBadgeClass(trade.side.toUpperCase()))}>
                      {trade.side}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums text-foreground/80">
                    {formatQuantity(trade.qty)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right font-mono text-xs tabular-nums text-foreground/80">
                    {trade.entry_price != null ? formatUSD(trade.entry_price) : NO_DATA}
                    <span className="text-muted-foreground/70"> → </span>
                    {trade.exit_price != null ? formatUSD(trade.exit_price) : NO_DATA}
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
                      <span className="text-xs text-muted-foreground/70">{NO_DATA}</span>
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
    <div className={feedPanelClass}>
      {/* Header */}
      <div className={feedHeaderClass}>
        <p className={feedTitleClass}>{UI_COPY.panels.agentActivity}</p>
        <div className="flex items-center gap-2">
          <span className={cn('h-2 w-2 rounded-full', activityDotClass(activityIndicator))} />
          <span className="font-mono text-xs text-muted-foreground">
            {activityLabel(activityIndicator)}
          </span>
        </div>
      </div>

      {logs.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-12">
          <Activity className="h-9 w-9 text-muted-foreground/40" aria-hidden />
          <p className="text-sm text-muted-foreground">{UI_COPY.empty.agentActivity}</p>
        </div>
      ) : (
        <div className="relative max-h-[480px] divide-y overflow-y-auto">
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
              : UI_COPY.tradingView.agentFallback
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
                    <span className="text-xs font-bold text-foreground/80">{displayName}</span>
                    {symbol && (
                      <span className="font-mono text-2xs text-muted-foreground/70">{symbol}</span>
                    )}
                    {action && action !== '' && (
                      <span className={cn('rounded px-1.5 py-0.5 text-3xs font-semibold tracking-caps', actionBadgeClass(action))}>
                        {action}
                      </span>
                    )}
                    {confPct != null && (
                      <span className={cn('font-mono text-3xs font-semibold', confColor)}>
                        {confPct}%
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {typeof log?.trace_id === 'string' && log.trace_id ? (
                      <button
                        onClick={() => setActiveTraceId(log.trace_id as string)}
                        className="font-mono text-3xs text-muted-foreground/70 transition-colors hover:text-foreground/70"
                      >
                        {(log.trace_id as string).slice(0, 8)}…
                      </button>
                    ) : null}
                    <span className="font-mono text-3xs text-muted-foreground/70">
                      {formatTimeAgo(ts)}
                    </span>
                  </div>
                </div>
                {msg && <p className="text-xs leading-snug text-foreground/70">{msg}</p>}
              </div>
            )
          })}
          <div className="pointer-events-none sticky bottom-0 h-8 bg-gradient-to-t from-card to-transparent dark:from-popover" />
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
      ? `${formatUSD(stats.realized)} ${UI_COPY.tradingView.realized} · ${formatUSD(stats.unrealized)} ${UI_COPY.tradingView.unrealized}`
      : pnlSummary != null
        ? `${formatUSD(pnlSummary.realized_pnl)} ${UI_COPY.tradingView.realized} · ${formatUSD(pnlSummary.unrealized_pnl)} ${UI_COPY.tradingView.unrealized}`
        : undefined

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <TradeStat
          label={UI_COPY.tradingView.statSessionPnl}
          value={stats.totalPnl < -0.005 ? `(${formatUSD(stats.totalPnl)})` : formatUSD(stats.totalPnl)}
          sub={pnlSub}
          sign={pnlSign}
          icon={stats.totalPnl >= 0 ? TrendingUp : TrendingDown}
        />
        <TradeStat
          label={UI_COPY.tradingView.statWinRate}
          value={stats.winRatePct != null ? `${stats.winRatePct.toFixed(1)}%` : NO_DATA}
          sub={
            stats.totalTrades > 0
              ? `${stats.wins} ${UI_COPY.tradingView.subOf} ${stats.totalTrades} ${UI_COPY.tradingView.closed}`
              : UI_COPY.tradingView.subNoClosedTrades
          }
          sign={winRateSign}
        />
        <TradeStat label={UI_COPY.tradingView.statTotalFills} value={String(stats.fills)} sub={UI_COPY.tradingView.subCompleted} />
        <TradeStat
          label={UI_COPY.tradingView.statOpenPositions}
          value={String(stats.activePositions)}
          sub={stats.activePositions === 1 ? UI_COPY.tradingView.subPosition : UI_COPY.tradingView.subPositions}
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
