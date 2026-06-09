'use client'

import { cn } from '@/lib/utils'
import type { SymbolView } from './types'

export const TIMEFRAMES = ['1m', '5m', '15m', '1h'] as const
export type Timeframe = (typeof TIMEFRAMES)[number]

/** Chart panel header: symbol, large price, day change, O/H/L, timeframe tabs. */
export function SymbolHeader({
  view,
  timeframe,
  setTimeframe,
}: {
  view: SymbolView
  timeframe: Timeframe
  setTimeframe: (tf: Timeframe) => void
}) {
  const up = view.changePct >= 0
  return (
    <header className="flex h-[var(--term-hdr)] shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-800 px-3">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-base font-bold text-slate-100">{view.sym}</span>
        <span className="hidden text-[11px] text-slate-500 sm:inline">{view.name}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-lg font-bold tabular-nums text-slate-100">{view.price.toFixed(2)}</span>
        <span className={cn('font-mono text-xs font-semibold tabular-nums', up ? 'txt-up' : 'txt-down')}>
          {up ? '+' : ''}
          {view.changeAbs.toFixed(2)} ({up ? '+' : ''}
          {view.changePct.toFixed(2)}%)
        </span>
      </div>
      <div className="hidden items-center gap-3 font-mono text-[11px] tabular-nums text-slate-400 md:flex">
        <span>
          O <span className="text-slate-300">{view.dayOpen.toFixed(2)}</span>
        </span>
        <span>
          H <span className="text-slate-300">{view.dayHigh.toFixed(2)}</span>
        </span>
        <span>
          L <span className="text-slate-300">{view.dayLow.toFixed(2)}</span>
        </span>
      </div>
      <div className="ml-auto flex items-center gap-0.5 rounded-lg bg-slate-950 p-0.5">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => setTimeframe(tf)}
            className={cn(
              'rounded px-2 py-1 font-mono text-[11px] transition-colors',
              timeframe === tf ? 'bg-slate-800 text-[var(--accent)]' : 'text-slate-500 hover:text-slate-300',
            )}
          >
            {tf}
          </button>
        ))}
      </div>
    </header>
  )
}
