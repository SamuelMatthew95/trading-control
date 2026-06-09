'use client'

import { useMemo } from 'react'
import { useLivePnl } from '@/hooks/useLivePnl'
import { useLivePositions } from '@/hooks/useLivePositions'
import { getField, getStr, positionQty, toFiniteNum } from '@/lib/formatters'

/** Real paper starting capital (api.constants.DEFAULT_PAPER_CASH). */
export const STARTING_CASH = 100_000

export interface TerminalAccount {
  equity: number
  dayPnl: number
  buyingPower: number
}

/**
 * Real account stats for the shell header, derived from the canonical live P&L
 * (realized + mark-to-market unrealized) and the real open positions — the same
 * sources the rest of the dashboard uses, so the header can never disagree.
 */
export function useTerminalAccount(): TerminalAccount {
  const pnl = useLivePnl()
  const positions = useLivePositions()
  return useMemo(() => {
    const longNotional = positions.reduce((sum, p) => {
      const side = getStr(p, 'side').toLowerCase()
      if (side === 'short' || side === 'sell') return sum
      const qty = Math.abs(positionQty(p))
      const entry = toFiniteNum(getField(p, 'entry_price')) ?? 0
      return sum + entry * qty
    }, 0)
    return {
      equity: STARTING_CASH + pnl.total,
      dayPnl: pnl.total,
      buyingPower: STARTING_CASH - longNotional,
    }
  }, [pnl, positions])
}
