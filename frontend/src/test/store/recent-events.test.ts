import { describe, it, expect, beforeEach } from 'vitest'

import { useDashboardStore } from '@/stores/useDashboardStore'

// Covers the store half of the Live Activity fix: trackWsMessage must retain the
// symbol/price/change the WS frame carries (it used to drop them, leaving every
// market row as a bare "Market event"). The render half is covered by
// buildActivityTimeline tests.
describe('trackWsMessage — recent event detail', () => {
  beforeEach(() => {
    useDashboardStore.setState({ recentEvents: [], streamStats: {}, wsMessageCount: 0 })
  })

  it('carries symbol/price/change onto the recent event', () => {
    useDashboardStore.getState().trackWsMessage({
      stream: 'market_events',
      msgId: 'm1',
      timestamp: '2026-06-05T10:00:00Z',
      symbol: 'BTC/USD',
      price: 60781.58,
      change: -12.3,
      eventType: 'price_update',
    })
    const ev = useDashboardStore.getState().recentEvents[0]
    expect(ev.symbol).toBe('BTC/USD')
    expect(ev.price).toBe(60781.58)
    expect(ev.change).toBe(-12.3)
    expect(ev.eventType).toBe('price_update')
    expect(ev.stream).toBe('market_events')
  })

  it('defaults detail fields to null when the frame has no subject', () => {
    useDashboardStore
      .getState()
      .trackWsMessage({ stream: 'signals', msgId: 's1', timestamp: '2026-06-05T10:00:00Z' })
    const ev = useDashboardStore.getState().recentEvents[0]
    expect(ev.symbol).toBeNull()
    expect(ev.price).toBeNull()
    expect(ev.change).toBeNull()
  })
})
