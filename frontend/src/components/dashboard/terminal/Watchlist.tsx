'use client'

import { cn } from '@/lib/utils'
import { Panel } from './Panel'
import { Spark } from './Spark'
import { signClass } from './marketData'
import type { WatchRow } from './types'

/** Left-column watchlist of the real monitored symbols. Click a row to focus
 *  the chart / blotter / agent panels on that symbol. */
export function Watchlist({
  rows,
  active,
  onSelect,
}: {
  rows: WatchRow[]
  active: string
  onSelect: (sym: string) => void
}) {
  return (
    <Panel title="Watchlist" count={rows.length} bodyClass="overflow-y-auto thin-scroll" className="h-full">
      <table className="w-full table-fixed">
        <colgroup>
          <col />
          <col style={{ width: '58px' }} />
          <col style={{ width: '74px' }} />
        </colgroup>
        <tbody>
          {rows.map((r) => {
            const isActive = r.sym === active
            const up = r.changePct >= 0
            return (
              <tr
                key={r.sym}
                onClick={() => onSelect(r.sym)}
                className={cn(
                  'cursor-pointer border-l-2 transition-colors',
                  isActive
                    ? 'border-l-[var(--accent)] bg-slate-100 dark:bg-slate-800/50'
                    : 'border-l-transparent hover:bg-slate-50 dark:hover:bg-slate-800/30',
                )}
              >
                <td className="py-1.5 pl-3 pr-1">
                  <div className="font-mono text-[13px] font-bold text-slate-900 dark:text-slate-100">{r.sym}</div>
                  <div className="truncate text-[10px] text-slate-500">{r.name}</div>
                </td>
                <td className="px-0 py-1.5">
                  <Spark data={r.spark} up={up} />
                </td>
                <td className="py-1.5 pl-1 pr-3 text-right">
                  <div className="font-mono text-[13px] tabular-nums text-slate-900 dark:text-slate-100">
                    {r.price > 0 ? r.price.toFixed(2) : '--'}
                  </div>
                  <div className={cn('font-mono text-[10px] tabular-nums', signClass(r.changePct))}>
                    {up ? '+' : ''}
                    {r.changePct.toFixed(2)}%
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Panel>
  )
}
