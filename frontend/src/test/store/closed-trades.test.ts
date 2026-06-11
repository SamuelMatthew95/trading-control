import { afterEach, describe, expect, it } from 'vitest'

import { normalizeClosedTrade, useDashboardStore } from '@/stores/useDashboardStore'

afterEach(() => {
  useDashboardStore.setState({ closedTrades: [] })
})

describe('normalizeClosedTrade', () => {
  it('normalizes a memory-mode row (epoch-seconds timestamp, string numerics)', () => {
    // Shape produced by InMemoryStore.add_closed_trade / RedisStore.push_closed_trade.
    const trade = normalizeClosedTrade({
      symbol: 'BTC/USD',
      side: 'sell',
      qty: '0.5',
      entry_price: 40000,
      exit_price: 39973,
      pnl: -13.5,
      pnl_percent: -0.0675,
      timestamp: 1781067192.96,
    })
    expect(trade.symbol).toBe('BTC/USD')
    expect(trade.side).toBe('sell')
    expect(trade.qty).toBe(0.5)
    expect(trade.pnl).toBe(-13.5)
    // Epoch seconds are detected and converted to an ISO string.
    expect(trade.closed_at).toBe(new Date(1781067192960).toISOString())
  })

  it('prefers the ISO filled_at over the epoch timestamp and nulls bad numerics', () => {
    const trade = normalizeClosedTrade({
      symbol: 'ETH/USD',
      side: 'buy',
      qty: 'not-a-number',
      pnl: '',
      filled_at: '2026-06-10T12:00:00+00:00',
      timestamp: 1781067192.96,
    })
    expect(trade.qty).toBeNull()
    expect(trade.pnl).toBeNull()
    expect(trade.closed_at).toBe('2026-06-10T12:00:00+00:00')
  })
})

describe('hydrateDashboard → closedTrades', () => {
  it('replaces the closed-trades ledger wholesale from the REST snapshot', () => {
    useDashboardStore.getState().hydrateDashboard({
      closed_trades: [
        { symbol: 'BTC/USD', side: 'sell', pnl: -13.5, filled_at: '2026-06-10T12:00:00Z' },
        { symbol: 'SOL/USD', side: 'sell', pnl: 4.2, timestamp: 1781067000 },
        'garbage-row',
      ],
    })
    const trades = useDashboardStore.getState().closedTrades
    expect(trades).toHaveLength(2)
    expect(trades[0].symbol).toBe('BTC/USD')
    expect(trades[1].pnl).toBe(4.2)
  })

  it('keeps the previous ledger when the snapshot omits closed_trades', () => {
    useDashboardStore.setState({
      closedTrades: [
        {
          symbol: 'BTC/USD',
          side: 'sell',
          qty: 1,
          entry_price: 1,
          exit_price: 2,
          pnl: 1,
          pnl_percent: 100,
          closed_at: null,
        },
      ],
    })
    useDashboardStore.getState().hydrateDashboard({})
    expect(useDashboardStore.getState().closedTrades).toHaveLength(1)
  })
})
