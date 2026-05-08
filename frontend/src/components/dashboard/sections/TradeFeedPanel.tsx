'use client'

import { TerminalCard, SectionHeader, EmptyState } from '@/components/terminal'
import { TradeSideChip, GradeChip, PnlValue } from '@/components/trading'
import { formatCurrency, toFiniteNumber } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { TRADE_FEED_MAX_ROWS } from '@/lib/constants/trading'
import {
  ROW_BETWEEN,
  ROW_DIVIDER_SKIP_FIRST,
  ROW_END,
  ROW_START,
  SCROLL_LIST_TRADE_FEED,
  SYMBOL_LABEL,
  TRACE_BUTTON,
} from '@/lib/styles'
import { cn } from '@/lib/utils'
import type { TradeFeedItem } from '@/stores/useCodexStore'

interface TradeFeedPanelProps {
  trades: TradeFeedItem[]
  onTraceClick: (traceId: string) => void
}

interface TradeFeedRowProps {
  trade: TradeFeedItem
  onTraceClick: (traceId: string) => void
}

function formatQtyAndPrice(qty: number | null, exitPrice: number | null): string {
  const qtyText = qty != null ? String(qty) : '—'
  return `${qtyText} @ ${formatCurrency(exitPrice)}`
}

function TraceLinkButton(props: { traceId: string; onTraceClick: (id: string) => void }) {
  const { traceId, onTraceClick } = props
  const handleClick = () => onTraceClick(traceId)
  return (
    <button onClick={handleClick} className={TRACE_BUTTON}>
      trace:{traceId.slice(0, 8)}…
    </button>
  )
}

function TradePnlCell(props: { pnl: number | null; pnlPct: number | null }) {
  if (props.pnl == null) return <span className={UI_TEXT.muted}>—</span>
  return <PnlValue value={props.pnl} percent={props.pnlPct} />
}

const TRADE_FEED_ROW = cn('flex flex-wrap py-2', ROW_BETWEEN, ROW_DIVIDER_SKIP_FIRST)
const TRADE_FEED_ROW_LEFT = cn('min-w-0', ROW_START)

function TradeFeedRow(props: TradeFeedRowProps) {
  const { trade, onTraceClick } = props
  const exitPrice = toFiniteNumber(trade.exit_price)
  const qty = toFiniteNumber(trade.qty)
  const pnl = toFiniteNumber(trade.pnl)
  const pnlPct = toFiniteNumber(trade.pnl_percent)

  return (
    <div className={TRADE_FEED_ROW}>
      <div className={TRADE_FEED_ROW_LEFT}>
        <TradeSideChip side={trade.side} />
        <span className={SYMBOL_LABEL}>{trade.symbol}</span>
        <span className={UI_TEXT.muted}>{formatQtyAndPrice(qty, exitPrice)}</span>
      </div>
      <div className={ROW_END}>
        <TradePnlCell pnl={pnl} pnlPct={pnlPct} />
        <GradeChip grade={trade.grade} />
        {trade.execution_trace_id ? (
          <TraceLinkButton traceId={trade.execution_trace_id} onTraceClick={onTraceClick} />
        ) : null}
      </div>
    </div>
  )
}

export function TradeFeedPanel(props: TradeFeedPanelProps) {
  const { trades, onTraceClick } = props
  return (
    <TerminalCard>
      <SectionHeader
        title="Trade Feed"
        right={<span className={UI_TEXT.muted}>{trades.length} fills</span>}
      />
      {trades.length === 0 ? (
        <EmptyState message="No orders today" />
      ) : (
        <div className={SCROLL_LIST_TRADE_FEED}>
          {trades.slice(0, TRADE_FEED_MAX_ROWS).map((trade) => (
            <TradeFeedRow key={trade.id} trade={trade} onTraceClick={onTraceClick} />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}
