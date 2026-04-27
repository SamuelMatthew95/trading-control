'use client'

import { memo } from 'react'
import { cn } from '@/lib/utils'
import { AgentStream } from '@/components/dashboard/AgentStream'
import { PositionsTable } from '@/components/dashboard/PositionsTable'
import type { TradeFeedItem } from '@/stores/useCodexStore'
import { dashboardCardClass, dashboardMutedClass, dashboardSectionTitleClass } from '@/components/dashboard/uiTokens'

type PositionRecord = Record<string, unknown>

const formatUSD = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return '$0.00'
  return `$${Math.abs(value).toFixed(2)}`
}

function toFiniteNumber(value: unknown): number | null {
  const cast = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(cast) ? cast : null
}

export const TradingConsoleSection = memo(function TradingConsoleSection({
  tradeFeed,
  positions,
  realAgentsCount,
  wsConnected,
  hasSyncDrift,
  agentLogs,
  formatAgentMessage,
  onClosePosition,
  onViewPositionDetails,
}: {
  tradeFeed: TradeFeedItem[]
  positions: PositionRecord[]
  realAgentsCount: number
  wsConnected: boolean
  hasSyncDrift: boolean
  agentLogs: Array<Record<string, unknown>>
  formatAgentMessage: (raw: unknown) => string
  onClosePosition: (position: PositionRecord) => void
  onViewPositionDetails: (position: PositionRecord) => void
}) {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <div className="space-y-4 xl:col-span-3">
        <div className={dashboardCardClass}>
          <div className="mb-3 flex items-center justify-between">
            <p className={dashboardSectionTitleClass}>System Stats</p>
            <span className={dashboardMutedClass}>Live</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <p className={dashboardMutedClass}>Trades</p>
              <p className="text-sm font-mono tabular-nums text-slate-100">{tradeFeed.length}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <p className={dashboardMutedClass}>Positions</p>
              <p className="text-sm font-mono tabular-nums text-slate-100">{positions.length}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <p className={dashboardMutedClass}>Agents</p>
              <p className="text-sm font-mono tabular-nums text-slate-100">{realAgentsCount}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <p className={dashboardMutedClass}>WS</p>
              <p className={cn('text-sm font-mono tabular-nums', wsConnected ? 'text-emerald-400' : 'text-amber-400')}>
                {wsConnected ? 'Connected' : 'Reconnecting'}
              </p>
            </div>
          </div>
        </div>

        <div className={dashboardCardClass}>
          <div className="mb-3 flex items-center justify-between">
            <p className={dashboardSectionTitleClass}>Trade Feed</p>
            <p className={dashboardMutedClass}>{tradeFeed.length} fills</p>
          </div>
          {tradeFeed.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-700 px-4 py-8 text-center text-xs font-sans text-slate-500">
              Awaiting fills...
            </div>
          ) : (
            <div className="max-h-96 overflow-y-auto space-y-1">
              {tradeFeed.slice(0, 20).map((trade) => {
                const isBuy = trade.side === 'buy'
                const pnl = toFiniteNumber(trade.pnl)
                const pnlPct = toFiniteNumber(trade.pnl_percent)
                const isPnlPositive = (pnl ?? 0) >= 0
                const exitPrice = toFiniteNumber(trade.exit_price)
                const qty = toFiniteNumber(trade.qty)

                return (
                  <div key={trade.id} className="flex items-center justify-between gap-2 border-t border-slate-200 py-2 first:border-t-0 dark:border-slate-800">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', isBuy ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400')}>
                        {isBuy ? 'BUY' : 'SELL'}
                      </span>
                      <span className="text-sm font-mono font-semibold text-slate-100">{trade.symbol}</span>
                      <span className={dashboardMutedClass}>
                        {qty != null ? qty : '--'} @ {exitPrice != null ? formatUSD(exitPrice) : '--'}
                      </span>
                    </div>
                    <span className={cn('text-xs font-mono tabular-nums font-semibold', isPnlPositive ? 'text-emerald-400' : 'text-rose-400')}>
                      {pnl == null ? '--' : `${isPnlPositive ? '+' : '-'}${formatUSD(pnl)}${pnlPct != null ? ` (${isPnlPositive ? '+' : ''}${pnlPct.toFixed(1)}%)` : ''}`}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <div className="space-y-4 xl:col-span-5">
        {hasSyncDrift && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-300">
            Sync drift warning: realtime events are present, but lifecycle rows are 0.
          </div>
        )}
        <AgentStream logs={agentLogs} formatMessage={formatAgentMessage} />
      </div>

      <div className="space-y-4 xl:col-span-4">
        <div className={dashboardCardClass}>
          <p className={dashboardSectionTitleClass}>Portfolio Summary</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <p className={dashboardMutedClass}>Open Positions</p>
              <p className="text-sm font-mono tabular-nums text-slate-100">{positions.length}</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <p className={dashboardMutedClass}>Unrealized P&amp;L</p>
              <p className="text-sm font-mono tabular-nums text-slate-100">
                {formatUSD(positions.reduce((sum, position) => sum + (toFiniteNumber(position?.pnl) ?? 0), 0))}
              </p>
            </div>
          </div>
        </div>

        <PositionsTable positions={positions} onClose={onClosePosition} onViewDetails={onViewPositionDetails} />
      </div>
    </div>
  )
})
