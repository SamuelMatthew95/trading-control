'use client'

import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { sentimentTextClass } from '@/lib/design/sentiment'
import { actionTextClass } from '@/lib/dashboard-helpers'
import { Panel } from './Panel'
import { formatUSD, formatQuantity, formatTimestamp } from '@/lib/formatters'
import type { TradeFeedItem } from '@/stores/useDashboardStore'

/** Recent REAL executions/fills produced by the ExecutionEngine (trade feed). */
export function ExecutionsPanel({ trades }: { trades: TradeFeedItem[] }) {
  return (
    <Panel title={UI_COPY.panels.executions} count={trades.length} bodyClass="overflow-y-auto thin-scroll">
      {trades.length === 0 ? (
        <div className="flex h-full items-center justify-center py-8 text-xs text-muted-foreground">
          {UI_COPY.empty.fills}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-[auto_1fr_auto_auto] gap-x-2 px-3 pb-1 pt-1.5 text-3xs font-semibold uppercase tracking-caps text-muted-foreground">
            <span>{UI_COPY.tables.side}</span>
            <span>{UI_COPY.tables.symbol}</span>
            <span className="text-right">{UI_COPY.tables.qty}</span>
            <span className="text-right">{UI_COPY.tables.pnl}</span>
          </div>
          <div className="divide-y divide-border">
            {trades.slice(0, 40).map((t) => {
              const price = t.exit_price ?? t.entry_price
              const pnl = t.pnl
              return (
                <div
                  key={t.id}
                  className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-x-2 px-3 py-1.5 font-mono text-2xs tabular-nums"
                >
                  <span className={actionTextClass(t.side)}>{t.side.toUpperCase()}</span>
                  <span className="truncate">
                    <span className="font-bold text-foreground">{t.symbol || NO_DATA}</span>
                    {price != null && <span className="ml-1.5 text-muted-foreground">@{price.toFixed(2)}</span>}
                  </span>
                  <span className="text-right text-foreground/70">
                    {t.qty != null ? formatQuantity(t.qty) : NO_DATA}
                  </span>
                  <span className={cn('text-right font-semibold', pnl == null ? 'text-muted-foreground' : sentimentTextClass(pnl))}>
                    {pnl == null ? NO_DATA : `${pnl >= 0 ? '+' : '-'}${formatUSD(pnl)}`}
                  </span>
                </div>
              )
            })}
          </div>
          <div className="px-3 pb-1 pt-0.5 text-right font-mono text-3xs text-muted-foreground/70">
            {formatTimestamp(trades[0]?.filled_at ?? trades[0]?.created_at ?? null)}
          </div>
        </>
      )}
    </Panel>
  )
}
