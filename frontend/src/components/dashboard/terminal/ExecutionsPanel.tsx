'use client'

import { cn } from '@/lib/utils'
import { Panel } from './Panel'
import { formatUSD, formatQuantity, formatTimestamp } from '@/lib/formatters'
import { signClass } from './marketData'
import type { TradeFeedItem } from '@/stores/useDashboardStore'

/** Recent REAL executions/fills produced by the ExecutionEngine (trade feed). */
export function ExecutionsPanel({ trades }: { trades: TradeFeedItem[] }) {
  return (
    <Panel title="Executions" count={trades.length} bodyClass="overflow-y-auto thin-scroll">
      {trades.length === 0 ? (
        <div className="flex h-full items-center justify-center py-8 text-[12px] text-slate-500 dark:text-slate-600">
          No fills yet
        </div>
      ) : (
        <>
          <div className="grid grid-cols-[auto_1fr_auto_auto] gap-x-2 px-3 pb-1 pt-1.5 text-[9px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-600">
            <span>Side</span>
            <span>Symbol</span>
            <span className="text-right">Qty</span>
            <span className="text-right">P&L</span>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800/60">
            {trades.slice(0, 40).map((t) => {
              const price = t.exit_price ?? t.entry_price
              const pnl = t.pnl
              return (
                <div
                  key={t.id}
                  className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-x-2 px-3 py-1.5 font-mono text-[11px] tabular-nums"
                >
                  <span className={t.side === 'sell' ? 'txt-down' : 'txt-up'}>{t.side.toUpperCase()}</span>
                  <span className="truncate">
                    <span className="font-bold text-slate-900 dark:text-slate-100">{t.symbol || '--'}</span>
                    {price != null && <span className="ml-1.5 text-slate-500">@{price.toFixed(2)}</span>}
                  </span>
                  <span className="text-right text-slate-600 dark:text-slate-300">
                    {t.qty != null ? formatQuantity(t.qty) : '--'}
                  </span>
                  <span className={cn('text-right font-semibold', pnl == null ? 'text-slate-500' : signClass(pnl))}>
                    {pnl == null ? '--' : `${pnl >= 0 ? '+' : '-'}${formatUSD(pnl)}`}
                  </span>
                </div>
              )
            })}
          </div>
          <div className="px-3 pb-1 pt-0.5 text-right font-mono text-[9px] text-slate-400 dark:text-slate-600">
            {formatTimestamp(trades[0]?.filled_at ?? trades[0]?.created_at ?? null)}
          </div>
        </>
      )}
    </Panel>
  )
}
