'use client'

import { TerminalCard, SectionHeader, EmptyState } from '@/components/terminal'
import { TradeSideChip, GradeChip, PnlValue } from '@/components/trading'
import { cn } from '@/lib/utils'
import { formatCurrency, toFiniteNumber } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { TRADE_FEED_MAX_ROWS } from '@/lib/constants/trading'
import type { TradeFeedItem } from '@/stores/useCodexStore'

interface TradeFeedPanelProps {
  trades: TradeFeedItem[]
  onTraceClick: (traceId: string) => void
}

export function TradeFeedPanel({ trades, onTraceClick }: TradeFeedPanelProps) {
  return (
    <TerminalCard>
      <SectionHeader
        title="Trade Feed"
        right={<span className={UI_TEXT.muted}>{trades.length} fills</span>}
      />
      {trades.length === 0 ? (
        <EmptyState message="No orders today" />
      ) : (
        <div className="max-h-96 space-y-1 overflow-y-auto">
          {trades.slice(0, TRADE_FEED_MAX_ROWS).map((trade) => (
            <TradeFeedRow key={trade.id} trade={trade} onTraceClick={onTraceClick} />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}

interface TradeFeedRowProps {
  trade: TradeFeedItem
  onTraceClick: (traceId: string) => void
}

function TradeFeedRow({ trade, onTraceClick }: TradeFeedRowProps) {
  const exitPrice = toFiniteNumber(trade.exit_price)
  const qty = toFiniteNumber(trade.qty)
  const pnl = toFiniteNumber(trade.pnl)
  const pnlPct = toFiniteNumber(trade.pnl_percent)

  return (
    <div
      className={cn(
        'flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 py-2 first:border-t-0 dark:border-slate-800',
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <TradeSideChip side={trade.side} />
        <span className="text-sm font-mono font-semibold text-slate-900 dark:text-slate-100">
          {trade.symbol}
        </span>
        <span className={UI_TEXT.muted}>
          {qty != null ? qty : '—'} @ {formatCurrency(exitPrice)}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {pnl != null ? (
          <PnlValue value={pnl} percent={pnlPct} />
        ) : (
          <span className={UI_TEXT.muted}>—</span>
        )}
        <GradeChip grade={trade.grade} />
        {trade.execution_trace_id ? (
          <button
            onClick={() => onTraceClick(trade.execution_trace_id!)}
            className="rounded-[4px] px-1.5 py-0.5 text-[10px] font-mono text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
          >
            trace:{trade.execution_trace_id.slice(0, 8)}…
          </button>
        ) : null}
      </div>
    </div>
  )
}
