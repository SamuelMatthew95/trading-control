'use client'

import { useMemo } from 'react'
import { useLivePositions } from '@/hooks/useLivePositions'
import { cn } from '@/lib/utils'
import {
  formatQuantity,
  formatUSD,
  getField,
  getStr,
  isActivePosition,
  positionCostBasis,
  positionMarketValue,
  positionQty,
  reconciledMarketValue,
  toFiniteNum as toNum,
} from '@/lib/formatters'
import { Layers } from 'lucide-react'
import { LiveNumber } from '@/components/dashboard/LiveNumber'
import { positionSideBadgeClass } from '@/lib/dashboard-helpers'

// `Invested` (cost basis) and `Value` (current market value) are the two numbers
// that make the row legible to a human — "I put in $X, it is worth $Y now" — and
// are what the bare Qty/Entry/Current/P&L layout was missing. `title` tooltips
// spell out each formula so the columns are self-explanatory.
const COLUMNS: ReadonlyArray<{ label: string; align: 'left' | 'right'; title?: string }> = [
  { label: 'Symbol', align: 'left' },
  { label: 'Side', align: 'left' },
  { label: 'Qty', align: 'right' },
  { label: 'Entry', align: 'right', title: 'Average entry price' },
  { label: 'Current', align: 'right', title: 'Latest market price' },
  { label: 'Invested', align: 'right', title: 'Cost basis — entry price × quantity (the cash you put in)' },
  { label: 'Value', align: 'right', title: 'What the position is worth now (Invested + P&L)' },
  { label: 'P&L', align: 'right' },
  { label: 'P&L %', align: 'right' },
]

/**
 * Open Positions table — the detail behind the "Active Positions" headline count.
 *
 * Reads `positions` straight from the store so it is a drop-in panel for any
 * section. Only rows with a non-zero quantity are shown (a flat row is a closed
 * position, not an open one); the badge reports that same active count, so the
 * panel can never contradict the Overview's "Active Positions" KPI.
 */
export function OpenPositionsPanel() {
  // Live-marked positions: P&L / current price re-valued against the price stream
  // every tick, so the table moves with the market instead of freezing between
  // backend position pushes.
  const positions = useLivePositions()
  const openPositions = useMemo(() => positions.filter(isActivePosition), [positions])

  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Open Positions
        </p>
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {openPositions.length} active
        </span>
      </div>

      {openPositions.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-12">
          <Layers className="h-9 w-9 text-slate-300 dark:text-slate-700" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No open positions</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                {COLUMNS.map(({ label, align, title }, i) => (
                  <th
                    key={label}
                    title={title}
                    className={cn(
                      'py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400',
                      align === 'right' ? 'text-right' : 'text-left',
                      i === 0 ? 'pl-5 pr-4' : 'px-4',
                      'last:pr-5',
                    )}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {openPositions.map((pos, i) => {
                const pnl = toNum(getField(pos, 'pnl'))
                const pnlPct = toNum(getField(pos, 'pnl_percent'))
                const isPos = (pnl ?? 0) >= 0
                const side = getStr(pos, 'side').toUpperCase()
                const symbol = getStr(pos, 'symbol') || '--'
                // ORM uses `quantity`; paper-broker Redis state uses `qty` — positionQty tries both.
                const qty = positionQty(pos)
                const entryPrice = toNum(getField(pos, 'entry_price'))
                const currentPrice = toNum(getField(pos, 'current_price'))
                // The cash put in vs what it is worth now. Positions are already
                // live-marked (useLivePositions), so these agree with the Entry /
                // Current / P&L cells: Value − Invested == P&L.
                const invested = positionCostBasis(pos)
                // Derive Value from rounded Invested + P&L so the row's arithmetic
                // ties out at the 2dp the user sees (Invested − Value === −P&L).
                // Three independently-rounded numbers otherwise fail the eyeball
                // subtraction (11.28 − 10.14 reads as 1.14 while P&L shows 1.15).
                // P&L stays anchored to the live value shown in the header. For a
                // LONG this equals current×qty exactly; for a SHORT it is
                // cost-basis + P&L (the row still ties out) rather than the buy-back
                // market value — an accepted trade-off for an internally consistent row.
                const marketValue =
                  invested != null && pnl != null ? reconciledMarketValue(invested, pnl) : positionMarketValue(pos)

                return (
                  <tr
                    key={`${symbol}-${i}`}
                    className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <td className="py-3 pl-5 pr-4 font-mono font-bold text-slate-900 dark:text-slate-100">
                      {symbol}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('rounded-md px-2 py-0.5 text-[11px] font-semibold', positionSideBadgeClass(side))}>
                        {side || '--'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {formatQuantity(qty)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {entryPrice != null ? formatUSD(entryPrice) : '--'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {currentPrice != null ? formatUSD(currentPrice) : '--'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums font-semibold text-slate-900 dark:text-slate-100">
                      {invested != null ? formatUSD(invested) : '--'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {marketValue != null ? formatUSD(marketValue) : '--'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {pnl != null ? (
                        <LiveNumber
                          value={pnl}
                          className={cn(
                            'font-semibold font-mono tabular-nums',
                            isPos ? 'text-emerald-500' : 'text-rose-500',
                          )}
                        >
                          {isPos ? '+' : '-'}{formatUSD(pnl)}
                        </LiveNumber>
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
