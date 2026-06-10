'use client'

import { useMemo } from 'react'
import { useDashboardStore, type Order, type Position } from '@/stores/useDashboardStore'
import { getField, isActivePosition, positionLivePnl, toFiniteNum } from '@/lib/formatters'

export interface LivePnl {
  /** Realized P&L from filled orders. */
  realized: number
  /** Live mark-to-market unrealized P&L across open positions. */
  unrealized: number
  /** realized + unrealized. */
  total: number
  /** True when there is at least one order or open position to report. */
  hasData: boolean
}

/**
 * Canonical live P&L: realized (filled orders) plus live mark-to-market
 * unrealized (open positions valued at the latest streamed price). One
 * definition shared by the header chip and the overview headline so they can
 * never show two different "total P&L" numbers. Pure for unit testing.
 */
export function computeLivePnl(
  orders: Order[],
  positions: Position[],
  prices: Record<string, unknown>,
): LivePnl {
  const realized = orders.reduce((sum, order) => sum + (toFiniteNum(getField(order, 'pnl')) ?? 0), 0)
  const unrealized = positions.reduce((sum, pos) => sum + (positionLivePnl(pos, prices) ?? 0), 0)
  const hasData = orders.length > 0 || positions.some(isActivePosition)
  return { realized, unrealized, total: realized + unrealized, hasData }
}

export function useLivePnl(): LivePnl {
  const orders = useDashboardStore((s) => s.orders)
  const positions = useDashboardStore((s) => s.positions)
  const prices = useDashboardStore((s) => s.prices)
  return useMemo(() => computeLivePnl(orders, positions, prices), [orders, positions, prices])
}
