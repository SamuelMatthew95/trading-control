'use client'

import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { sentimentTextClass, TONE_DOT, TONE_TEXT } from '@/lib/design/sentiment'
import type { SymbolView } from './types'

/** Chart panel header: symbol, name, live price, session change + O/H/L. */
export function SymbolHeader({ view, live }: { view: SymbolView; live: boolean }) {
  const up = view.changePct >= 0
  const hasData = view.points.length > 1
  return (
    <header className="flex h-[var(--term-hdr)] shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b px-3">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-base font-bold text-foreground">{view.sym}</span>
        <span className="hidden text-2xs text-muted-foreground sm:inline">{view.name}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-lg font-bold tabular-nums text-foreground">
          {view.price > 0 ? view.price.toFixed(2) : NO_DATA}
        </span>
        {hasData && (
          <span className={cn('font-mono text-xs font-semibold tabular-nums', sentimentTextClass(view.changePct))}>
            {up ? '+' : ''}
            {view.changeAbs.toFixed(2)} ({up ? '+' : ''}
            {view.changePct.toFixed(2)}%)
          </span>
        )}
      </div>
      {hasData && (
        <div className="hidden items-center gap-3 font-mono text-2xs tabular-nums text-muted-foreground md:flex">
          <span>
            {UI_COPY.terminal.open} <span className="text-foreground/80">{view.open.toFixed(2)}</span>
          </span>
          <span>
            {UI_COPY.terminal.high} <span className="text-foreground/80">{view.high.toFixed(2)}</span>
          </span>
          <span>
            {UI_COPY.terminal.low} <span className="text-foreground/80">{view.low.toFixed(2)}</span>
          </span>
        </div>
      )}
      {/* Real L1 best bid/ask from the Alpaca quote — only when two-sided. */}
      {view.bid != null && view.ask != null && (
        <div className="hidden items-center gap-3 font-mono text-2xs tabular-nums text-muted-foreground lg:flex">
          <span>
            {UI_COPY.terminal.bid} <span className={TONE_TEXT.success}>{view.bid.toFixed(2)}</span>
          </span>
          <span>
            {UI_COPY.terminal.ask} <span className={TONE_TEXT.danger}>{view.ask.toFixed(2)}</span>
          </span>
          <span>
            {UI_COPY.terminal.spread}{' '}
            <span className="text-foreground/80">{(view.ask - view.bid).toFixed(2)}</span>
          </span>
        </div>
      )}
      <div className="ml-auto flex items-center gap-1.5">
        <span className={cn('h-1.5 w-1.5 rounded-full', live ? `animate-pulse ${TONE_DOT.success}` : TONE_DOT.neutral)} />
        <span className="font-mono text-3xs uppercase tracking-caps text-muted-foreground">
          {live ? UI_COPY.status.live : UI_COPY.status.idle}
        </span>
      </div>
    </header>
  )
}
