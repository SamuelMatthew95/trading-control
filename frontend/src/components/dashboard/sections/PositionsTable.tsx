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

interface PositionsTableProps {
  positions: Position[]
}

const HEADERS = ['Symbol', 'Side', 'Qty', 'Entry', 'Current', 'P&L', 'P&L %'] as const

export function PositionsTable({ positions }: PositionsTableProps) {
  return (
    <TerminalCard padded>
      <SectionHeader title="Open Positions" />
      <TerminalTable headers={HEADERS} rightAlignedColumns={[2, 3, 4, 5, 6]}>
        {positions.length === 0 ? (
          <TerminalRow>
            <TerminalCell colSpan={HEADERS.length} padded>
              <EmptyState message="No open positions" />
            </TerminalCell>
          </TerminalRow>
        ) : (
          positions.map((position, index) => {
            const pnl = toFiniteNumber(position?.pnl)
            const pnlPct = toFiniteNumber(position?.pnl_percent)
            const tone = getNumberTone(pnl)
            const symbol = String(position?.symbol ?? '—')
            return (
              <TerminalRow key={`${symbol}-${index}`}>
                <TerminalCell numeric>{symbol}</TerminalCell>
                <TerminalCell>
                  <TradeSideChip side={position?.side} />
                </TerminalCell>
                <TerminalCell numeric align="right">
                  {position?.quantity ?? '—'}
                </TerminalCell>
                <TerminalCell numeric align="right">
                  {formatCurrency(toFiniteNumber(position?.entry_price))}
                </TerminalCell>
                <TerminalCell numeric align="right">
                  {formatCurrency(toFiniteNumber(position?.current_price))}
                </TerminalCell>
                <TerminalCell align="right" className={cn('font-mono tabular-nums font-semibold', TONE_CLASSES[tone].text)}>
                  <PnlValue value={pnl} className="text-sm" />
                </TerminalCell>
                <TerminalCell align="right" className={cn('font-mono tabular-nums text-xs', TONE_CLASSES[tone].text)}>
                  {pnlPct == null ? '—' : formatPercent(pnlPct)}
                </TerminalCell>
              </TerminalRow>
            )
          })
        )}
      </TerminalTable>
    </TerminalCard>
  )
}
