'use client'

import { cn } from '@/lib/utils'
import type { SymbolView } from './types'

/** Chart panel header: symbol, name, live price, session change + O/H/L. */
export function SymbolHeader({ view, live }: { view: SymbolView; live: boolean }) {
  const up = view.changePct >= 0
  const hasData = view.points.length > 1
  return (
    <header className="flex h-[var(--term-hdr)] shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-200 px-3 dark:border-slate-800">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-base font-bold text-slate-900 dark:text-slate-100">{view.sym}</span>
        <span className="hidden text-[11px] text-slate-500 sm:inline">{view.name}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-lg font-bold tabular-nums text-slate-900 dark:text-slate-100">
          {view.price > 0 ? view.price.toFixed(2) : '--'}
        </span>
        {hasData && (
          <span className={cn('font-mono text-xs font-semibold tabular-nums', up ? 'txt-up' : 'txt-down')}>
            {up ? '+' : ''}
            {view.changeAbs.toFixed(2)} ({up ? '+' : ''}
            {view.changePct.toFixed(2)}%)
          </span>
        )}
      </div>
      {hasData && (
        <div className="hidden items-center gap-3 font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400 md:flex">
          <span>
            O <span className="text-slate-700 dark:text-slate-300">{view.open.toFixed(2)}</span>
          </span>
          <span>
            H <span className="text-slate-700 dark:text-slate-300">{view.high.toFixed(2)}</span>
          </span>
          <span>
            L <span className="text-slate-700 dark:text-slate-300">{view.low.toFixed(2)}</span>
          </span>
        </div>
      )}
      {/* Real L1 best bid/ask from the Alpaca quote — only when two-sided. */}
      {view.bid != null && view.ask != null && (
        <div className="hidden items-center gap-3 font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400 lg:flex">
          <span>
            BID <span className="txt-up">{view.bid.toFixed(2)}</span>
          </span>
          <span>
            ASK <span className="txt-down">{view.ask.toFixed(2)}</span>
          </span>
          <span>
            SPR{' '}
            <span className="text-slate-700 dark:text-slate-300">
              {(view.ask - view.bid).toFixed(2)}
            </span>
          </span>
        </div>
      )}
      <div className="ml-auto flex items-center gap-1.5">
        <span className={cn('h-1.5 w-1.5 rounded-full', live ? 'animate-pulse bg-[var(--up)]' : 'bg-slate-400')} />
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{live ? 'Live' : 'Idle'}</span>
      </div>
    </header>
  )
}
