import { useCodexStore, type Order, type Position } from '@/stores/useCodexStore'

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
    useCodexStore.setState({ orders: [], positions: [] })
  })

  it('normalizes REST "buy" side to "long"', () => {
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'buy' })],
    })
    const [order] = useCodexStore.getState().orders
    expect(order.side).toBe('long')
  })

  it('normalizes REST "sell" side to "short"', () => {
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'sell' })],
    })
    const [order] = useCodexStore.getState().orders
    expect(order.side).toBe('short')
  })

  it('preserves already-normalized "long" side', () => {
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'long' })],
    })
    expect(useCodexStore.getState().orders[0].side).toBe('long')
  })

  it('preserves already-normalized "short" side', () => {
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ side: 'short' })],
    })
    expect(useCodexStore.getState().orders[0].side).toBe('short')
  })

  it('deduplicates by order_id when merging with existing WS orders', () => {
    useCodexStore.setState({ orders: [makeOrder({ order_id: 'o1', side: 'long', pnl: 99 })] })
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ order_id: 'o1', side: 'buy', pnl: 5 })],
    })
    const orders = useCodexStore.getState().orders
    expect(orders).toHaveLength(1)
    expect(orders[0].side).toBe('long')
    expect(orders[0].pnl).toBe(5) // REST wins for same id
  })

  it('keeps WS-only orders not present in REST snapshot', () => {
    useCodexStore.setState({ orders: [makeOrder({ order_id: 'ws-only', side: 'short' })] })
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      orders: [makeOrder({ order_id: 'rest-only', side: 'sell' })],
    })
    const ids = useCodexStore.getState().orders.map((o) => o.order_id)
    expect(ids).toContain('rest-only')
    expect(ids).toContain('ws-only')
  })
})

describe('hydrateDashboard — positions merge', () => {
  beforeEach(() => {
    useCodexStore.setState({ orders: [], positions: [] })
  })

  it('accepts REST positions and stores them', () => {
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.2 })],
    })
    expect(useCodexStore.getState().positions).toHaveLength(1)
    expect(useCodexStore.getState().positions[0].quantity).toBe(0.2)
  })

  it('REST position overwrites WS position for the same symbol', () => {
    useCodexStore.setState({ positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.5 })] })
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.2 })],
    })
    const positions = useCodexStore.getState().positions
    expect(positions).toHaveLength(1)
    expect(positions[0].quantity).toBe(0.2)
  })

  it('keeps WS-only positions for symbols absent from REST snapshot', () => {
    useCodexStore.setState({ positions: [makePosition({ symbol: 'ETH/USD', quantity: 1.0 })] })
    useCodexStore.getState().hydrateDashboard({
      ...baseData(),
      positions: [makePosition({ symbol: 'BTC/USD', quantity: 0.1 })],
    })
    const symbols = useCodexStore.getState().positions.map((p) => p.symbol)
    expect(symbols).toContain('BTC/USD')
    expect(symbols).toContain('ETH/USD')
    expect(useCodexStore.getState().positions).toHaveLength(2)
  })

  it('skips update when positions field is absent', () => {
    useCodexStore.setState({ positions: [makePosition({ symbol: 'BTC/USD' })] })
    useCodexStore.getState().hydrateDashboard({ ...baseData() })
    expect(useCodexStore.getState().positions).toHaveLength(1)
  })

  it('keeps existing positions when REST sends an empty array (treat empty as no-data)', () => {
    useCodexStore.setState({ positions: [makePosition({ symbol: 'BTC/USD' })] })
    useCodexStore.getState().hydrateDashboard({ ...baseData(), positions: [] })
    // Empty REST snapshot = "no data available" — WS positions are preserved.
    // A genuine "all positions closed" should come through as a non-empty REST
    // update overwriting each symbol individually.
    expect(useCodexStore.getState().positions).toHaveLength(1)
  })
})
