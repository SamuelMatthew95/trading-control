'use client'

import {
  TerminalCard,
  SectionHeader,
  EmptyState,
  TerminalTable,
  TerminalRow,
  TerminalCell,
} from '@/components/terminal'
import { TradeSideChip, PnlValue } from '@/components/trading'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone } from '@/lib/state'
import { formatCurrency, formatPercent, toFiniteNumber } from '@/lib/format'
import type { Position } from '@/stores/useCodexStore'

const HEADERS = ['Symbol', 'Side', 'Qty', 'Entry', 'Current', 'P&L', 'P&L %'] as const

interface PositionsTableProps {
  positions: Position[]
}

interface PositionRowProps {
  position: Position
  index: number
}

function readSymbol(position: Position): string {
  return String(position?.symbol ?? '—')
}

function readQuantity(position: Position): string {
  return position?.quantity != null ? String(position.quantity) : '—'
}

function PositionRow(props: PositionRowProps) {
  const { position, index } = props
  const pnl = toFiniteNumber(position?.pnl)
  const pnlPct = toFiniteNumber(position?.pnl_percent)
  const tone = getNumberTone(pnl)
  const symbol = readSymbol(position)
  const pnlPctText = pnlPct == null ? '—' : formatPercent(pnlPct)

  return (
    <TerminalRow key={`${symbol}-${index}`}>
      <TerminalCell numeric>{symbol}</TerminalCell>
      <TerminalCell>
        <TradeSideChip side={position?.side} />
      </TerminalCell>
      <TerminalCell numeric align="right">
        {readQuantity(position)}
      </TerminalCell>
      <TerminalCell numeric align="right">
        {formatCurrency(toFiniteNumber(position?.entry_price))}
      </TerminalCell>
      <TerminalCell numeric align="right">
        {formatCurrency(toFiniteNumber(position?.current_price))}
      </TerminalCell>
      <TerminalCell
        align="right"
        className={cn('font-mono tabular-nums font-semibold', TONE_CLASSES[tone].text)}
      >
        <PnlValue value={pnl} className="text-sm" />
      </TerminalCell>
      <TerminalCell
        align="right"
        className={cn('font-mono tabular-nums text-xs', TONE_CLASSES[tone].text)}
      >
        {pnlPctText}
      </TerminalCell>
    </TerminalRow>
  )
}

function EmptyPositionsRow() {
  return (
    <TerminalRow>
      <TerminalCell colSpan={HEADERS.length} padded>
        <EmptyState message="No open positions" />
      </TerminalCell>
    </TerminalRow>
  )
}

export function PositionsTable(props: PositionsTableProps) {
  const { positions } = props
  return (
    <TerminalCard padded>
      <SectionHeader title="Open Positions" />
      <TerminalTable headers={HEADERS} rightAlignedColumns={[2, 3, 4, 5, 6]}>
        {positions.length === 0 ? (
          <EmptyPositionsRow />
        ) : (
          positions.map((position, index) => (
            <PositionRow key={`${readSymbol(position)}-${index}`} position={position} index={index} />
          ))
        )}
      </TerminalTable>
    </TerminalCard>
  )
}
