import { useDashboardStore, type Order, type Position } from '@/stores/useDashboardStore'

const BASE_TIMESTAMP = '2026-01-01T00:00:00.000Z'

function makeOrder(overrides: Partial<Record<string, unknown>> = {}): Order {
  return {
    order_id: 'o1',
    symbol: 'BTC/USD',
    side: 'long',
    quantity: 0.1,
    entry_price: 50000,
    current_price: 50000,
    pnl: 0,
    timestamp: BASE_TIMESTAMP,
    ...overrides,
  } as Order
}

function makePosition(overrides: Partial<Record<string, unknown>> = {}): Position {
  return {
    symbol: 'BTC/USD',
    side: 'long',
    quantity: 0.1,
    entry_price: 50000,
    current_price: 50000,
    pnl: 0,
    ...overrides,
  } as Position
}

function baseData() {
  return { timestamp: BASE_TIMESTAMP }
}

describe('hydrateDashboard — orders side normalization', () => {
  beforeEach(() => {
    useDashboardStore.setState({ orders: [], positions: [] })
  })

  it('normalizes REST "buy" side to "long"', () => {
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'buy' })],
    })
    const [order] = useDashboardStore.getState().orders
    expect(order.side).toBe('long')
  })

  it('normalizes REST "sell" side to "short"', () => {
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'sell' })],
    })
    const [order] = useDashboardStore.getState().orders
    expect(order.side).toBe('short')
  })

  it('preserves already-normalized "long" side', () => {
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'long' })],
    })
    expect(useDashboardStore.getState().orders[0].side).toBe('long')
  })

  it('preserves already-normalized "short" side', () => {
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'short' })],
    })
    expect(useDashboardStore.getState().orders[0].side).toBe('short')
  })

  it('deduplicates by order_id when merging with existing WS orders', () => {
    useDashboardStore.setState({ orders: [makeOrder({ order_id: 'o1', side: 'long', pnl: 99 })] })
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ order_id: 'o1', side: 'buy', pnl: 5 })],
    })
    const orders = useDashboardStore.getState().orders
    expect(orders).toHaveLength(1)
    expect(orders[0].side).toBe('long')
    expect(orders[0].pnl).toBe(5) // REST wins for same id
  })

  it('keeps WS-only orders not present in REST snapshot', () => {
    useDashboardStore.setState({ orders: [makeOrder({ order_id: 'ws-only', side: 'short' })] })
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ order_id: 'rest-only', side: 'sell' })],
    })
    const ids = useDashboardStore.getState().orders.map((o) => o.order_id)
    expect(ids).toContain('rest-only')
    expect(ids).toContain('ws-only')
  })
})

describe('hydrateDashboard — positions merge', () => {
  beforeEach(() => {
    useDashboardStore.setState({ orders: [], positions: [] })
  })

  it('accepts REST positions and stores them', () => {
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.2 })],
    })
    expect(useDashboardStore.getState().positions).toHaveLength(1)
    expect(useDashboardStore.getState().positions[0].quantity).toBe(0.2)
  })

  it('REST position overwrites WS position for the same symbol', () => {
    useDashboardStore.setState({ positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.5 })] })
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.2 })],
    })
    const positions = useDashboardStore.getState().positions
    expect(positions).toHaveLength(1)
    expect(positions[0].quantity).toBe(0.2)
  })

  it('keeps WS-only positions for symbols absent from REST snapshot', () => {
    useDashboardStore.setState({ positions: [makePosition({ symbol: 'ETH/USD', quantity: 1.0 })] })
    useDashboardStore.getState().hydrateDashboard({
      ...baseData(),
      positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.1 })],
    })
    const symbols = useDashboardStore.getState().positions.map((p) => p.symbol)
    expect(symbols).toContain('BTC/USD')
    expect(symbols).toContain('ETH/USD')
    expect(useDashboardStore.getState().positions).toHaveLength(2)
  })

  it('skips update when positions field is absent', () => {
    useDashboardStore.setState({ positions: [makePosition({ symbol: 'BTC/USD' })] })
    useDashboardStore.getState().hydrateDashboard({ ...baseData() })
    expect(useDashboardStore.getState().positions).toHaveLength(1)
  })

  it('keeps existing positions when REST sends an empty array (treat empty as no-data)', () => {
    useDashboardStore.setState({ positions: [makePosition({ symbol: 'BTC/USD' })] })
    useDashboardStore.getState().hydrateDashboard({ ...baseData(), positions: [] })
    // Empty REST snapshot = "no data available" — WS positions are preserved.
    // A genuine "all positions closed" should come through as a non-empty REST
    // update overwriting each symbol individually.
    expect(useDashboardStore.getState().positions).toHaveLength(1)
  })
})
