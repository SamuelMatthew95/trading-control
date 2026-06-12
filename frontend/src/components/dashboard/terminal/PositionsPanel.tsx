'use client'

import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { sentimentTextClass } from '@/lib/design/sentiment'
import { toneForAction } from '@/lib/dashboard-helpers'
import { Badge } from '@/components/ui/badge'
import { Panel } from './Panel'
import { formatUSD, formatQuantity, getField, getStr, isActivePosition, positionQty, toFiniteNum } from '@/lib/formatters'
import type { Position } from '@/stores/useDashboardStore'

const COLS = [
  UI_COPY.tables.symbol,
  UI_COPY.tables.side,
  UI_COPY.tables.qty,
  UI_COPY.tables.avg,
  UI_COPY.tables.last,
  UI_COPY.tables.mktValue,
  UI_COPY.tables.pnl,
  UI_COPY.tables.pnlPct,
] as const

/**
 * Read-only blotter of the REAL open positions the agents hold (paper broker,
 * marked to the live price stream). No manual actions — the agents trade, this
 * observes.
 */
export function PositionsPanel({
  positions,
  onSelect,
}: {
  positions: Position[]
  onSelect: (symbol: string) => void
}) {
  const open = positions.filter(isActivePosition)
  const totalPnl = open.reduce((s, p) => s + (toFiniteNum(getField(p, 'pnl')) ?? 0), 0)

  return (
    <Panel
      title={UI_COPY.panels.positions}
      count={open.length}
      right={
        open.length > 0 ? (
          <span className="flex items-center gap-1.5 font-mono text-2xs tabular-nums">
            <span className="text-3xs uppercase tracking-caps text-muted-foreground">
              {UI_COPY.panels.unrealized}
            </span>
            <span className={cn('font-bold', sentimentTextClass(totalPnl))}>
              {totalPnl >= 0 ? '+' : '-'}
              {formatUSD(totalPnl)}
            </span>
          </span>
        ) : undefined
      }
      className="h-full"
      bodyClass="overflow-y-auto thin-scroll"
    >
      {open.length === 0 ? (
        <div className="flex h-full items-center justify-center py-10 text-xs text-muted-foreground">
          {UI_COPY.empty.positions}
        </div>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="sticky top-0 bg-card text-3xs uppercase tracking-caps text-muted-foreground dark:bg-popover">
              {COLS.map((h, i) => (
                <th key={h} className={cn('py-2 font-semibold', i === 0 ? 'pl-3 text-left' : 'px-3 text-right', i === 1 && '!text-left')}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {open.map((p, i) => {
              const symbol = getStr(p, 'symbol') || NO_DATA
              const side = getStr(p, 'side').toLowerCase()
              const qty = Math.abs(positionQty(p))
              const avg = toFiniteNum(getField(p, 'entry_price'))
              const last = toFiniteNum(getField(p, 'current_price'))
              const pnl = toFiniteNum(getField(p, 'pnl')) ?? 0
              const pnlPct = toFiniteNum(getField(p, 'pnl_percent'))
              const up = pnl >= 0
              return (
                <tr
                  key={`${symbol}-${i}`}
                  onClick={() => onSelect(symbol)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSelect(symbol)
                    }
                  }}
                  tabIndex={0}
                  className="cursor-pointer font-mono tabular-nums transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <td className="py-1.5 pl-3 text-left font-bold text-foreground">{symbol}</td>
                  <td className="px-3 text-left">
                    <Badge tone={toneForAction(side === 'short' ? 'sell' : 'buy')} size="xs" className="font-mono">
                      {side.toUpperCase() || NO_DATA}
                    </Badge>
                  </td>
                  <td className="px-3 text-right text-foreground/70">{formatQuantity(qty)}</td>
                  <td className="px-3 text-right text-muted-foreground">{avg != null ? avg.toFixed(2) : NO_DATA}</td>
                  <td className="px-3 text-right text-foreground/80">{last != null ? last.toFixed(2) : NO_DATA}</td>
                  <td className="px-3 text-right text-foreground/70">{last != null ? formatUSD(qty * last) : NO_DATA}</td>
                  <td className={cn('px-3 text-right font-semibold', sentimentTextClass(pnl))}>
                    {up ? '+' : '-'}
                    {formatUSD(pnl)}
                  </td>
                  <td className={cn('px-3 text-right', sentimentTextClass(pnl))}>
                    {pnlPct != null ? `${up ? '+' : ''}${pnlPct.toFixed(2)}%` : NO_DATA}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
