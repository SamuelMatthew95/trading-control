'use client'

import { create } from 'zustand'
import type { Position } from '@/stores/useCodexStore'
import { getStr, positionQty, toFiniteNum } from '@/lib/formatters'
import { universeBasePrice } from './marketData'
import type { OrderDraft, PaperPosition, ToastMessage, WorkingOrder } from './types'

/** Paper-desk starting cash. The terminal is the manual paper-trading companion
 *  to the autonomous bot (see design handoff), so it keeps its own cash base. */
export const STARTING_CASH = 100_000

// Deterministic demo book used only when the real account has no open positions,
// so the terminal renders a populated, lifelike desk out of the box. Always a
// PAPER book — the app trades paper, and the autonomous positions live on the
// Trading/System pages.
const DEMO_SEED: ReadonlyArray<{ symbol: string; side: 'long' | 'short'; qty: number; offset: number }> = [
  { symbol: 'NVDA', side: 'long', qty: 120, offset: -0.036 },
  { symbol: 'AAPL', side: 'long', qty: 80, offset: 0.002 },
  { symbol: 'TSLA', side: 'short', qty: 40, offset: 0.033 },
  { symbol: 'MSFT', side: 'long', qty: 25, offset: 0.0007 },
]

function markedPosition(
  symbol: string,
  side: 'long' | 'short',
  qty: number,
  avg: number,
  priceFor: (sym: string) => number,
): PaperPosition {
  const last = priceFor(symbol) || avg
  const dir = side === 'long' ? 1 : -1
  const pnl = (last - avg) * qty * dir
  const pnlPct = avg !== 0 ? ((last - avg) / avg) * 100 * dir : 0
  return { symbol, side, qty, avg, last, pnl, pnlPct }
}

interface PaperDeskState {
  cash: number
  positions: PaperPosition[]
  orders: WorkingOrder[]
  seeded: boolean
  /** Seed the desk once — from the real open positions when present, else demo. */
  seed: (realPositions: Position[], priceFor: (sym: string) => number) => void
  /** Re-mark every position to the latest price. */
  markToMarket: (priceFor: (sym: string) => number) => void
  /** Fill any working order the price has crossed; returns fill toasts. */
  fillWorking: (priceFor: (sym: string) => number) => ToastMessage[]
  /** Submit a ticket; market fills now, limit/stop rests. Returns a toast. */
  submit: (draft: OrderDraft) => ToastMessage
  flatten: (symbol: string, last: number) => ToastMessage
  cancel: (id: string) => void
}

function applyFill(positions: PaperPosition[], order: OrderDraft, fillPx: number): PaperPosition[] {
  const idx = positions.findIndex((p) => p.symbol === order.symbol)
  const dir = order.side === 'buy' ? 1 : -1
  if (idx === -1) {
    const side = order.side === 'sell' ? 'short' : 'long'
    return [...positions, { symbol: order.symbol, side, qty: order.qty, avg: fillPx, last: fillPx, pnl: 0, pnlPct: 0 }]
  }
  const p = positions[idx]
  const curDir = p.side === 'long' ? 1 : -1
  const newSigned = curDir * p.qty + dir * order.qty
  const next = positions.slice()
  if (newSigned === 0) {
    next.splice(idx, 1)
    return next
  }
  // Weighted-average cost only when adding to the same direction.
  let avg = p.avg
  if (curDir > 0 === dir > 0) {
    avg = (p.avg * p.qty + fillPx * order.qty) / (p.qty + order.qty)
  }
  next[idx] = { ...p, side: newSigned > 0 ? 'long' : 'short', qty: Math.abs(newSigned), avg }
  return next
}

export const usePaperDesk = create<PaperDeskState>((set, get) => ({
  cash: STARTING_CASH,
  positions: [],
  orders: [],
  seeded: false,

  seed: (realPositions, priceFor) => {
    if (get().seeded) return
    const real = realPositions.filter((p) => Math.abs(positionQty(p)) > 0)
    let positions: PaperPosition[]
    if (real.length > 0) {
      positions = real.map((p) => {
        const symbol = getStr(p, 'symbol')
        const sideRaw = getStr(p, 'side').toLowerCase()
        const qty = Math.abs(positionQty(p))
        const side: 'long' | 'short' = sideRaw === 'short' || sideRaw === 'sell' ? 'short' : 'long'
        const avg = toFiniteNum(p.entry_price) ?? (priceFor(symbol) || universeBasePrice(symbol))
        return markedPosition(symbol, side, qty, avg, priceFor)
      })
    } else {
      positions = DEMO_SEED.map((d) => {
        const ref = priceFor(d.symbol) || universeBasePrice(d.symbol)
        const avg = ref * (1 + d.offset)
        return markedPosition(d.symbol, d.side, d.qty, avg, priceFor)
      })
    }
    set({ positions, seeded: true })
  },

  markToMarket: (priceFor) =>
    set((state) => ({
      positions: state.positions.map((p) => markedPosition(p.symbol, p.side, p.qty, p.avg, priceFor)),
    })),

  fillWorking: (priceFor) => {
    const { orders } = get()
    if (orders.length === 0) return []
    const toasts: ToastMessage[] = []
    const remaining: WorkingOrder[] = []
    let positions = get().positions
    for (const o of orders) {
      const px = priceFor(o.symbol)
      const crossed =
        (o.type === 'limit' && o.side === 'buy' && px <= o.price) ||
        (o.type === 'limit' && o.side === 'sell' && px >= o.price) ||
        (o.type === 'stop' && o.side === 'buy' && px >= o.price) ||
        (o.type === 'stop' && o.side === 'sell' && px <= o.price)
      if (crossed) {
        positions = applyFill(positions, o, o.price)
        toasts.push({ kind: o.side, text: `Filled ${o.side.toUpperCase()} ${o.qty} ${o.symbol} @ ${o.price.toFixed(2)}` })
      } else {
        remaining.push(o)
      }
    }
    if (toasts.length > 0) set({ positions, orders: remaining })
    return toasts
  },

  submit: (draft) => {
    if (draft.type === 'market') {
      set((state) => ({ positions: applyFill(state.positions, draft, draft.price) }))
      return { kind: draft.side, text: `Filled ${draft.side.toUpperCase()} ${draft.qty} ${draft.symbol} @ ${draft.price.toFixed(2)}` }
    }
    const order: WorkingOrder = { ...draft, id: `O${Date.now()}`, t: Date.now() }
    set((state) => ({ orders: [order, ...state.orders] }))
    return {
      kind: 'work',
      text: `Working ${draft.type} ${draft.side.toUpperCase()} ${draft.qty} ${draft.symbol} @ ${draft.price.toFixed(2)}`,
    }
  },

  flatten: (symbol, last) => {
    set((state) => ({ positions: state.positions.filter((p) => p.symbol !== symbol) }))
    return { kind: 'flat', text: `Flattened ${symbol} @ ${last.toFixed(2)}` }
  },

  cancel: (id) => set((state) => ({ orders: state.orders.filter((o) => o.id !== id) })),
}))

export interface DeskAccount {
  equity: number
  dayPnl: number
  buyingPower: number
}

/** Derive account stats from the paper desk — used by both the shell header
 *  and the terminal so the two never disagree. */
export function deskAccount(cash: number, positions: PaperPosition[]): DeskAccount {
  const dayPnl = positions.reduce((s, p) => s + p.pnl, 0)
  const longNotional = positions.reduce((s, p) => s + (p.side === 'long' ? p.avg * p.qty : 0), 0)
  return { equity: cash + dayPnl, dayPnl, buyingPower: cash - longNotional }
}
