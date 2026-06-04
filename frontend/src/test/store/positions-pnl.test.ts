import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCodexStore } from '@/stores/useCodexStore'

const okJson = (body: unknown) =>
  ({ ok: true, json: async () => body }) as unknown as Response

afterEach(() => {
  vi.restoreAllMocks()
  useCodexStore.setState({ positions: [], pnlSummary: null })
})

describe('fetchPositions', () => {
  it('replaces positions for symbols the endpoint covers (merge by symbol)', async () => {
    // A pre-existing WS-only position for a symbol the endpoint does NOT return.
    useCodexStore.setState({
      positions: [
        { symbol: 'ETH/USD', side: 'long', quantity: 1, entry_price: 1, current_price: 1, pnl: 0 },
      ],
    })
    global.fetch = vi.fn().mockResolvedValue(
      okJson({
        positions: [
          {
            symbol: 'BTC/USD',
            side: 'long',
            quantity: 0.5,
            entry_price: 40000,
            current_price: 42000,
            pnl: 1000,
          },
        ],
        count: 1,
        source: 'in_memory',
      }),
    ) as unknown as typeof fetch

    await useCodexStore.getState().fetchPositions()

    const symbols = useCodexStore.getState().positions.map((p) => p.symbol).sort()
    expect(symbols).toEqual(['BTC/USD', 'ETH/USD'])
  })

  it('does not throw and leaves state intact on a non-ok response', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false } as Response) as unknown as typeof fetch
    await expect(useCodexStore.getState().fetchPositions()).resolves.toBeUndefined()
    expect(useCodexStore.getState().positions).toEqual([])
  })
})

describe('fetchPnl', () => {
  it('stores the live PnL summary (realized + unrealized)', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      okJson({
        closed_trades: [],
        open_positions: [],
        summary: {
          realized_pnl: 12.5,
          unrealized_pnl: 7.5,
          total_pnl: 20,
          closed_trades: 3,
          winning_trades: 2,
          win_rate_percent: 66.67,
          open_positions: 1,
        },
        source: 'in_memory',
      }),
    ) as unknown as typeof fetch

    await useCodexStore.getState().fetchPnl()

    const summary = useCodexStore.getState().pnlSummary
    expect(summary?.total_pnl).toBe(20)
    expect(summary?.unrealized_pnl).toBe(7.5)
  })
})
