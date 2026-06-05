import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'

// Live mark-to-market: Session P&L must value open positions against the price
// stream every tick, NOT freeze on the 30s REST `pnlSummary` snapshot. Seed a
// position that is up live while the snapshot still reads a stale figure, then
// assert the tile shows the live total and ignores the snapshot.
const { mockUseCodexStore } = vi.hoisted(() => {
  const store: Record<string, unknown> = {
    wsConnected: true,
    agentLogs: [],
    tradeFeed: [],
    performanceSummary: null,
    // Stale broker snapshot — should be overridden by live mark-to-market.
    pnlSummary: { total_pnl: 999, realized_pnl: 999, unrealized_pnl: 0 },
    orders: [{ pnl: 7 }],
    positions: [
      { symbol: 'BTC/USD', side: 'long', quantity: 2, entry_price: 100, current_price: 100, pnl: 0 },
    ],
    prices: { 'BTC/USD': { price: 150, updatedAt: new Date().toISOString() } },
  }
  const hook = Object.assign(
    (selector?: (s: typeof store) => unknown) =>
      typeof selector === 'function' ? selector(store) : store,
    { getState: () => store },
  )
  return { mockStore: store, mockUseCodexStore: hook }
})

vi.mock('@/stores/useCodexStore', () => ({
  useCodexStore: mockUseCodexStore,
}))

import { TradingView } from '@/components/dashboard/TradingView'

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch
})

describe('TradingView — Session P&L marks to market live', () => {
  it('values open positions against the live price stream, not the stale snapshot', () => {
    render(<TradingView setActiveTraceId={vi.fn()} />)

    // realized 7 + unrealized (150-100)*2 = 100 → live total 107.
    expect(screen.getByText('$107.00')).toBeInTheDocument()
    // The stale broker snapshot (999) must NOT win once there is a live position.
    expect(screen.queryByText('$999.00')).not.toBeInTheDocument()
  })

  it('spells out the live realized/unrealized split', () => {
    render(<TradingView setActiveTraceId={vi.fn()} />)
    expect(screen.getByText('$7.00 realized · $100.00 unrealized')).toBeInTheDocument()
  })
})
