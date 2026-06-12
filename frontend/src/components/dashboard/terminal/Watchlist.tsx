'use client'

import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { sentimentTextClass } from '@/lib/design/sentiment'
import { Panel } from './Panel'
import { Spark } from './Spark'
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
    <Panel
      title={UI_COPY.panels.watchlist}
      count={rows.length}
      bodyClass="overflow-y-auto thin-scroll"
      className="h-full"
    >
      <table className="w-full table-fixed">
        <colgroup>
          <col />
          <col className="w-14" />
          <col className="w-20" />
        </colgroup>
        <tbody>
          {rows.map((r) => {
            const isActive = r.sym === active
            const up = (r.changePct ?? 0) >= 0
            return (
              <tr
                key={r.sym}
                onClick={() => onSelect(r.sym)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect(r.sym)
                  }
                }}
                tabIndex={0}
                aria-selected={isActive}
                className={cn(
                  'cursor-pointer border-l-2 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                  isActive
                    ? 'border-l-brand bg-muted dark:bg-muted/50'
                    : 'border-l-transparent hover:bg-muted/50 dark:hover:bg-muted/30',
                )}
              >
                <td className="py-1.5 pl-3 pr-1">
                  <div className="font-mono text-sm font-bold text-foreground">{r.sym}</div>
                  <div className="truncate text-3xs text-muted-foreground">{r.name}</div>
                </td>
                <td className="px-0 py-1.5">
                  <Spark data={r.spark} up={up} />
                </td>
                <td className="py-1.5 pl-1 pr-3 text-right">
                  <div className="font-mono text-sm tabular-nums text-foreground">
                    {r.price != null ? r.price.toFixed(2) : NO_DATA}
                  </div>
                  {/* '--' until real movement exists — never a fake +0.00% */}
                  <div
                    className={cn(
                      'font-mono text-3xs tabular-nums',
                      r.changePct != null ? sentimentTextClass(r.changePct) : 'text-muted-foreground/60',
                    )}
                  >
                    {r.changePct != null ? `${up ? '+' : ''}${r.changePct.toFixed(2)}%` : NO_DATA}
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
