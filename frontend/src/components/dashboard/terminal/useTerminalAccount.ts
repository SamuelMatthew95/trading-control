'use client'

import { useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/apiClient'
import { useLivePnl } from '@/hooks/useLivePnl'
import { useLivePositions } from '@/hooks/useLivePositions'
import { getField, getStr, positionQty, toFiniteNum } from '@/lib/formatters'

/** Real paper starting capital (api.constants.DEFAULT_PAPER_CASH) — fallback
 *  only; the /account endpoint supplies the authoritative value. */
export const STARTING_CASH = 100_000

const ACCOUNT_POLL_MS = 10_000

export interface TerminalAccount {
  equity: number
  pnl: number
  buyingPower: number
}

interface BrokerAccount {
  cash: number
  startingCash: number
}

/** Signed live market value of the open positions (longs +, shorts −),
 *  marked client-side against the streaming prices every tick. */
function signedPositionsValue(positions: ReturnType<typeof useLivePositions>): number {
  return positions.reduce((sum, p) => {
    const qty = Math.abs(positionQty(p))
    if (qty === 0) return sum
    const side = getStr(p, 'side').toLowerCase()
    const mark =
      toFiniteNum(getField(p, 'current_price')) ?? toFiniteNum(getField(p, 'entry_price')) ?? 0
    return sum + (side === 'short' || side === 'sell' ? -qty : qty) * mark
  }, 0)
}

/**
 * Real account stats for the shell header.
 *
 * Cash comes from the broker's actual balance (GET /account — every agent fill
 * ever, survives restarts); equity = cash + live-marked positions, so the number
 * still moves with every price tick between the calm 10s polls. Until the
 * endpoint responds (or when it reports unavailable), falls back to deriving
 * from the canonical live P&L over the default starting cash.
 */
export function useTerminalAccount(): TerminalAccount {
  const pnl = useLivePnl()
  const positions = useLivePositions()
  const [broker, setBroker] = useState<BrokerAccount | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch(api('/account'))
        if (!res.ok) return
        const data = (await res.json()) as {
          cash?: number | null
          starting_cash?: number | null
          source?: string
        }
        const cash = toFiniteNum(data?.cash)
        if (!cancelled && data?.source === 'paper_broker' && cash != null) {
          setBroker({ cash, startingCash: toFiniteNum(data?.starting_cash) ?? STARTING_CASH })
        }
      } catch {
        // Keep the last good value; the next interval retries.
      }
    }
    load()
    const id = setInterval(load, ACCOUNT_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return useMemo(() => {
    if (broker != null) {
      const equity = broker.cash + signedPositionsValue(positions)
      return {
        equity,
        pnl: equity - broker.startingCash,
        buyingPower: broker.cash,
      }
    }
    // Fallback: live P&L (realized + mark-to-market) over the default base.
    const longNotional = positions.reduce((sum, p) => {
      const side = getStr(p, 'side').toLowerCase()
      if (side === 'short' || side === 'sell') return sum
      const qty = Math.abs(positionQty(p))
      const entry = toFiniteNum(getField(p, 'entry_price')) ?? 0
      return sum + entry * qty
    }, 0)
    return {
      equity: STARTING_CASH + pnl.total,
      pnl: pnl.total,
      buyingPower: STARTING_CASH - longNotional,
    }
  }, [broker, positions, pnl])
}
