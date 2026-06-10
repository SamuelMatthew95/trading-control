import { describe, it, expect } from 'vitest'
import {
  livePriceFor,
  positionLivePnl,
  positionLivePnlPct,
  pricesFreshnessMs,
} from '@/lib/formatters'
import { markPositionsToMarket } from '@/hooks/useLivePositions'
import { computeLivePnl } from '@/hooks/useLivePnl'
import type { Order, Position } from '@/stores/useDashboardStore'

const pos = (overrides: Record<string, unknown>): Position =>
  ({ symbol: 'BTC/USD', side: 'long', quantity: 1, entry_price: 100, current_price: 100, pnl: 0, ...overrides }) as unknown as Position

describe('positionLivePnl — mark to market', () => {
  it('values a long against the live price stream', () => {
    expect(positionLivePnl(pos({ quantity: 2, entry_price: 100 }), { 'BTC/USD': { price: 110 } })).toBe(20)
  })

  it('values a short (entry - price)', () => {
    expect(positionLivePnl(pos({ side: 'short', quantity: 1, entry_price: 100 }), { 'BTC/USD': { price: 90 } })).toBe(10)
  })

  it('infers short from a negative quantity', () => {
    expect(positionLivePnl(pos({ side: '', quantity: -1, entry_price: 100 }), { 'BTC/USD': { price: 90 } })).toBe(10)
  })

  it('falls back to stored current_price when no live price exists', () => {
    expect(positionLivePnl(pos({ quantity: 1, entry_price: 100, current_price: 120 }), {})).toBe(20)
  })

  it('returns the stored pnl when entry price is unknown', () => {
    expect(positionLivePnl(pos({ entry_price: undefined, pnl: 5 }), {})).toBe(5)
  })

  it('returns 0 for a flat position', () => {
    expect(positionLivePnl(pos({ quantity: 0 }), { 'BTC/USD': { price: 999 } })).toBe(0)
  })
})

describe('positionLivePnlPct', () => {
  it('is the return on cost basis', () => {
    expect(positionLivePnlPct(pos({ quantity: 2, entry_price: 100 }), { 'BTC/USD': { price: 110 } })).toBe(10)
  })
})

describe('livePriceFor', () => {
  it('prefers the live price, then current_price, then entry', () => {
    expect(livePriceFor(pos({ current_price: 105 }), { 'BTC/USD': { price: 110 } })).toBe(110)
    expect(livePriceFor(pos({ current_price: 105 }), {})).toBe(105)
    expect(livePriceFor(pos({ current_price: undefined, entry_price: 100 }), {})).toBe(100)
  })
})

describe('pricesFreshnessMs', () => {
  it('returns null for an empty map', () => {
    expect(pricesFreshnessMs({})).toBeNull()
  })

  it('returns a small age for a just-updated price', () => {
    const ms = pricesFreshnessMs({ 'BTC/USD': { price: 1, updatedAt: new Date().toISOString() } })
    expect(ms).not.toBeNull()
    expect(ms as number).toBeGreaterThanOrEqual(0)
    expect(ms as number).toBeLessThan(5_000)
  })
})

describe('markPositionsToMarket', () => {
  it('re-marks pnl/current_price/pnl_percent when a live price exists', () => {
    const [marked] = markPositionsToMarket(
      [pos({ quantity: 1, entry_price: 100, current_price: 100, pnl: 0 })],
      { 'BTC/USD': { price: 150 } },
    )
    expect(marked.pnl).toBe(50)
    expect(marked.current_price).toBe(150)
    expect(marked.pnl_percent).toBe(50)
  })

  it('leaves positions untouched when no live price exists', () => {
    const input = pos({ pnl: 7 })
    const [marked] = markPositionsToMarket([input], {})
    expect(marked).toBe(input)
  })
})

describe('computeLivePnl', () => {
  it('sums realized orders and live unrealized positions', () => {
    const orders = [{ pnl: 10 }, { pnl: -3 }] as unknown as Order[]
    const positions = [pos({ quantity: 1, entry_price: 100, current_price: 130, pnl: 0 })]
    const r = computeLivePnl(orders, positions, {})
    expect(r.realized).toBe(7)
    expect(r.unrealized).toBe(30)
    expect(r.total).toBe(37)
    expect(r.hasData).toBe(true)
  })

  it('reports no data for empty inputs', () => {
    expect(computeLivePnl([], [], {})).toEqual({ realized: 0, unrealized: 0, total: 0, hasData: false })
  })
})
