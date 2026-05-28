import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import {
  PnlClarity,
  computePnlClarity,
} from '@/components/dashboard/system/PnlClarity'
import type { Position, TradeFeedItem } from '@/stores/useCodexStore'

const buildTrade = (overrides: Partial<TradeFeedItem> = {}): TradeFeedItem =>
  ({
    id: 'trade-1',
    symbol: 'BTC/USD',
    side: 'buy',
    qty: 1,
    entry_price: 100,
    exit_price: 110,
    pnl: 10,
    pnl_percent: 10,
    order_id: null,
    execution_trace_id: null,
    signal_trace_id: null,
    ...overrides,
  }) as TradeFeedItem

const buildPosition = (pnl: number): Position => ({
  symbol: 'BTC/USD',
  side: 'long',
  quantity: 1,
  entry_price: 100,
  current_price: 105,
  pnl,
})

describe('computePnlClarity', () => {
  it('returns zeros for empty inputs', () => {
    const r = computePnlClarity([], [])
    expect(r).toEqual({
      realizedPnl: 0,
      unrealizedPnl: 0,
      totalTrades: 0,
      wins: 0,
      winRatePct: 0,
    })
  })

  it('sums realized pnl across all trades with pnl set', () => {
    const r = computePnlClarity(
      [buildTrade({ pnl: 10 }), buildTrade({ id: 'trade-2', pnl: -5 })],
      [],
    )
    expect(r.realizedPnl).toBe(5)
    expect(r.totalTrades).toBe(2)
    expect(r.wins).toBe(1)
    expect(r.winRatePct).toBe(50)
  })

  it('sums unrealized pnl from positions', () => {
    const r = computePnlClarity([], [buildPosition(7), buildPosition(-3)])
    expect(r.unrealizedPnl).toBe(4)
  })

  it('skips trades with null pnl in count', () => {
    const r = computePnlClarity(
      [buildTrade({ pnl: 5 }), buildTrade({ id: 't-2', pnl: null })],
      [],
    )
    expect(r.totalTrades).toBe(1)
    expect(r.realizedPnl).toBe(5)
  })
})

describe('PnlClarity component', () => {
  it('shows -- when no trades and no positions', () => {
    render(<PnlClarity tradeFeed={[]} positions={[]} resolvedPerformanceSummary={null} />)
    // Multiple cells with --
    expect(screen.getAllByText('--').length).toBeGreaterThanOrEqual(4)
  })

  it('shows realized pnl when trades present', () => {
    render(
      <PnlClarity
        tradeFeed={[buildTrade({ pnl: 100 })]}
        positions={[]}
        resolvedPerformanceSummary={null}
      />,
    )
    expect(screen.getByText('Realized')).toBeInTheDocument()
  })

  it('shows win rate breakdown when trades present', () => {
    render(
      <PnlClarity
        tradeFeed={[buildTrade({ pnl: 5 }), buildTrade({ id: 't-2', pnl: -2 })]}
        positions={[]}
        resolvedPerformanceSummary={null}
      />,
    )
    expect(screen.getByText(/1 wins \/ 2 trades/)).toBeInTheDocument()
  })

  it('shows db total when resolved summary provided', () => {
    render(
      <PnlClarity
        tradeFeed={[]}
        positions={[]}
        resolvedPerformanceSummary={{ total_pnl: 1234.56 }}
      />,
    )
    expect(screen.getByText('Total (DB)')).toBeInTheDocument()
  })

  it('renders all six labels', () => {
    render(<PnlClarity tradeFeed={[]} positions={[]} resolvedPerformanceSummary={null} />)
    for (const label of ['Realized', 'Unrealized', 'Session', 'Total (DB)', 'Trades', 'Win Rate']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })
})
