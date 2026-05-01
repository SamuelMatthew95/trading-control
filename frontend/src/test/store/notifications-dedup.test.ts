import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useCodexStore } from '@/stores/useCodexStore'

const baseTrade = {
  severity: 'INFO' as const,
  message: 'BUY BTC/USD filled | Fill $43,000.00 | Qty 0.05',
  notification_type: 'trade.buy_filled',
  stream_source: 'executions',
  action: 'buy',
  symbol: 'BTC/USD',
  qty: 0.05,
  fill_price: 43_000,
  notional: 2_150,
  pnl: null,
  pnl_percent: null,
  order_id: null,
  trace_id: 'trace-1',
  state: 'open' as const,
  timestamp: '2026-05-01T00:00:00.000Z',
}

describe('addNotification dedup by stable notification_id', () => {
  beforeEach(() => {
    useCodexStore.setState({ notifications: [] })
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem('codex.notifications')
    }
  })
  afterEach(() => {
    useCodexStore.setState({ notifications: [] })
  })

  it('dedups the same fill arriving twice (REST hydrate + WS broadcast)', () => {
    const stableId = 'trade:buy:BTC/USD:trace-1'
    useCodexStore.getState().addNotification({ ...baseTrade, notification_id: stableId })
    useCodexStore.getState().addNotification({ ...baseTrade, notification_id: stableId })

    const list = useCodexStore.getState().notifications
    expect(list).toHaveLength(1)
    expect(list[0].id).toBe(stableId)
  })

  it('treats two distinct fills as distinct even when timestamps are close', () => {
    useCodexStore
      .getState()
      .addNotification({ ...baseTrade, notification_id: 'trade:buy:BTC/USD:trace-1' })
    useCodexStore
      .getState()
      .addNotification({ ...baseTrade, notification_id: 'trade:buy:BTC/USD:trace-2', message: 'BUY BTC/USD filled #2' })

    const list = useCodexStore.getState().notifications
    expect(list).toHaveLength(2)
    expect(list.map((n) => n.id)).toEqual([
      'trade:buy:BTC/USD:trace-2',
      'trade:buy:BTC/USD:trace-1',
    ])
  })

  it('falls back to a generated id when notification_id is absent', () => {
    useCodexStore.getState().addNotification(baseTrade)
    const list = useCodexStore.getState().notifications
    expect(list).toHaveLength(1)
    expect(list[0].id).toMatch(/^\d+-/)
  })
})
