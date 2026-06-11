'use client'

import { useMemo } from 'react'
import { useDashboardStore, type Position } from '@/stores/useDashboardStore'
import {
  getField,
  getStr,
  livePriceFor,
  positionLivePnl,
  positionLivePnlPct,
  toFiniteNum,
} from '@/lib/formatters'

/**
 * Re-mark each position to the live price stream: overwrite `current_price`,
 * `pnl`, and `pnl_percent` with mark-to-market values whenever a fresh price
 * exists for the symbol. Positions whose symbol has no live price are returned
 * untouched (we keep whatever the backend last sent rather than blanking it).
 *
 * Pure (no React) so it is unit-testable; {@link useLivePositions} wraps it.
 */
export function markPositionsToMarket(
  positions: Position[],
  prices: Record<string, unknown>,
): Position[] {
  return positions.map((pos) => {
    const symbol = getStr(pos, 'symbol')
    const live = toFiniteNum(getField(getField(prices, symbol), 'price'))
    if (live == null) return pos
    const pnl = positionLivePnl(pos, prices)
    const pnlPct = positionLivePnlPct(pos, prices)
    return {
      ...pos,
      current_price: livePriceFor(pos, prices) ?? pos.current_price,
      pnl: pnl ?? pos.pnl,
      pnl_percent: pnlPct ?? pos.pnl_percent,
    }
  })
}

/**
 * Store positions, marked to the live price stream so unrealized P&L moves with
 * the market every tick instead of freezing at the last backend push.
 */
export function useLivePositions(): Position[] {
  const positions = useDashboardStore((s) => s.positions)
  const prices = useDashboardStore((s) => s.prices)
  return useMemo(() => markPositionsToMarket(positions, prices), [positions, prices])
}
