'use client'

import { cn } from '@/lib/utils'
import { Panel } from './Panel'
import { signClass } from './marketData'
import { formatUSD, formatQuantity, getField, getStr, isActivePosition, positionQty, toFiniteNum } from '@/lib/formatters'
import type { Position } from '@/stores/useDashboardStore'

const COLS = ['Symbol', 'Side', 'Qty', 'Avg', 'Last', 'Mkt Value', 'P&L', 'P&L%'] as const

/**
 * Read-only blotter of the REAL open positions the agents hold (paper broker,
 * marked to the live price stream). No manual actions — the agents trade, this
 * observes.
 */
export function PositionsPanel({
  positions,
  onSelect,
}: {
  positions: Position[]
  onSelect: (symbol: string) => void
}) {
  const open = positions.filter(isActivePosition)
  const totalPnl = open.reduce((s, p) => s + (toFiniteNum(getField(p, 'pnl')) ?? 0), 0)

  return (
    <Panel
      title="Positions"
      count={open.length}
      right={
        open.length > 0 ? (
          <span className="flex items-center gap-1.5 font-mono text-[11px] tabular-nums">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">Unrealized</span>
            <span className={cn('font-bold', signClass(totalPnl))}>
              {totalPnl >= 0 ? '+' : '-'}
              {formatUSD(totalPnl)}
            </span>
          </span>
        ) : undefined
      }
      className="h-full"
      bodyClass="overflow-y-auto thin-scroll"
    >
      {open.length === 0 ? (
        <div className="flex h-full items-center justify-center py-10 text-[12px] text-slate-500 dark:text-slate-600">
          No open positions
        </div>
      ) : (
        <table className="w-full text-[12px]">
          <thead>
            <tr className="sticky top-0 bg-white text-[9px] uppercase tracking-wider text-slate-500 dark:bg-slate-900">
              {COLS.map((h, i) => (
                <th key={h} className={cn('py-2 font-semibold', i === 0 ? 'pl-3 text-left' : 'px-3 text-right', i === 1 && '!text-left')}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
            {open.map((p, i) => {
              const symbol = getStr(p, 'symbol') || '--'
              const side = getStr(p, 'side').toLowerCase()
              const qty = Math.abs(positionQty(p))
              const avg = toFiniteNum(getField(p, 'entry_price'))
              const last = toFiniteNum(getField(p, 'current_price'))
              const pnl = toFiniteNum(getField(p, 'pnl')) ?? 0
              const pnlPct = toFiniteNum(getField(p, 'pnl_percent'))
              const up = pnl >= 0
              return (
                <tr
                  key={`${symbol}-${i}`}
                  onClick={() => onSelect(symbol)}
                  className="cursor-pointer font-mono tabular-nums hover:bg-slate-50 dark:hover:bg-slate-800/40"
                >
                  <td className="py-1.5 pl-3 text-left font-bold text-slate-900 dark:text-slate-100">{symbol}</td>
                  <td className="px-3 text-left">
                    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold', side === 'short' ? 'badge-down' : 'badge-up')}>
                      {side.toUpperCase() || '--'}
                    </span>
                  </td>
                  <td className="px-3 text-right text-slate-600 dark:text-slate-300">{formatQuantity(qty)}</td>
                  <td className="px-3 text-right text-slate-500 dark:text-slate-400">{avg != null ? avg.toFixed(2) : '--'}</td>
                  <td className="px-3 text-right text-slate-700 dark:text-slate-200">{last != null ? last.toFixed(2) : '--'}</td>
                  <td className="px-3 text-right text-slate-600 dark:text-slate-300">{last != null ? formatUSD(qty * last) : '--'}</td>
                  <td className={cn('px-3 text-right font-semibold', up ? 'txt-up' : 'txt-down')}>
                    {up ? '+' : '-'}
                    {formatUSD(pnl)}
                  </td>
                  <td className={cn('px-3 text-right', up ? 'txt-up' : 'txt-down')}>
                    {pnlPct != null ? `${up ? '+' : ''}${pnlPct.toFixed(2)}%` : '--'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
