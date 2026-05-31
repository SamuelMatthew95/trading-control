'use client'

import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { getField, signedUSD, toFiniteNum as toFiniteNumber } from '@/lib/formatters'
import { cn } from '@/lib/utils'

import { pnlColorClass } from './helpers'
import type { PerformanceSummaryLike } from './types'
import type { Position, TradeFeedItem } from '@/stores/useCodexStore'

interface PnlCellProps {
  label: string
  value: string
  sub?: string
  colorClass?: string
}

function PnlCell({ label, value, sub, colorClass }: PnlCellProps) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p
        className={cn(
          'mt-1 text-base font-mono tabular-nums font-semibold',
          colorClass ?? 'text-slate-900 dark:text-slate-100',
        )}
      >
        {value}
      </p>
      {sub ? (
        <p className="mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">{sub}</p>
      ) : null}
    </div>
  )
}

export interface PnlClarityComputation {
  realizedPnl: number
  unrealizedPnl: number
  totalTrades: number
  wins: number
  winRatePct: number
}

export function computePnlClarity(
  tradeFeed: TradeFeedItem[],
  positions: Position[],
): PnlClarityComputation {
  const realizedPnl = tradeFeed.reduce((sum, row) => sum + (row.pnl ?? 0), 0)
  const unrealizedPnl = positions.reduce(
    (sum, row) => sum + (toFiniteNumber(getField(row, 'pnl')) ?? 0),
    0,
  )
  const totalTrades = tradeFeed.filter((row) => row.pnl != null).length
  const wins = tradeFeed.filter((row) => (row.pnl ?? 0) > 0).length
  const winRatePct = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
  return { realizedPnl, unrealizedPnl, totalTrades, wins, winRatePct }
}

export interface PnlClarityProps {
  tradeFeed: TradeFeedItem[]
  positions: Position[]
  resolvedPerformanceSummary: PerformanceSummaryLike | null
}

export function PnlClarity({
  tradeFeed,
  positions,
  resolvedPerformanceSummary,
}: PnlClarityProps) {
  const { realizedPnl, unrealizedPnl, totalTrades, wins, winRatePct } = computePnlClarity(
    tradeFeed,
    positions,
  )
  const session = realizedPnl + unrealizedPnl
  const dbTotal = resolvedPerformanceSummary?.total_pnl ?? 0
  const sessionIsEmpty = totalTrades === 0 && positions.length === 0

  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>P&L Clarity</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <PnlCell
          label="Realized"
          value={totalTrades === 0 ? '--' : signedUSD(realizedPnl)}
          colorClass={pnlColorClass(realizedPnl, totalTrades === 0)}
        />
        <PnlCell
          label="Unrealized"
          value={positions.length === 0 ? '--' : signedUSD(unrealizedPnl)}
          colorClass={pnlColorClass(unrealizedPnl, positions.length === 0)}
        />
        <PnlCell
          label="Session"
          value={sessionIsEmpty ? '--' : signedUSD(session)}
          colorClass={pnlColorClass(session, sessionIsEmpty)}
        />
        <PnlCell
          label="Total (DB)"
          value={resolvedPerformanceSummary ? signedUSD(dbTotal) : '--'}
          colorClass={pnlColorClass(dbTotal, !resolvedPerformanceSummary)}
        />
        <PnlCell label="Trades" value={String(totalTrades)} />
        <PnlCell
          label="Win Rate"
          value={totalTrades === 0 ? '--' : `${winRatePct.toFixed(1)}%`}
          sub={totalTrades > 0 ? `${wins} wins / ${totalTrades} trades` : undefined}
        />
      </div>
    </div>
  )
}
