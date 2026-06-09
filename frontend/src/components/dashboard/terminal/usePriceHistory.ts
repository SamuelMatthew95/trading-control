'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/apiClient'
import type { PricePoint } from './types'

const REFRESH_MS = 8000
const EPOCH_MS_THRESHOLD = 10_000_000_000

/**
 * Real per-symbol intraday price history, fetched from the backend
 * `/dashboard/price-history` endpoint (reconstructed from the market_events
 * stream — the real prices the agents act on). Refreshed on a calm interval, not
 * hammered: the series grows as the poller publishes, so the chart and
 * sparklines show real movement immediately.
 */
export function usePriceHistory(): Record<string, PricePoint[]> {
  const [history, setHistory] = useState<Record<string, PricePoint[]>>({})

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch(api('/dashboard/price-history'))
        if (!res.ok) return
        const data = (await res.json()) as {
          history?: Record<string, Array<{ ts?: number; price?: number }>>
        }
        const raw = data?.history ?? {}
        const next: Record<string, PricePoint[]> = {}
        for (const [sym, series] of Object.entries(raw)) {
          next[sym] = (series ?? [])
            .map((pt) => {
              const tsNum = typeof pt.ts === 'number' ? pt.ts : Number(pt.ts)
              const t = Number.isFinite(tsNum) ? (tsNum > EPOCH_MS_THRESHOLD ? tsNum : tsNum * 1000) : 0
              return { t, p: Number(pt.price) }
            })
            .filter((pt) => Number.isFinite(pt.p) && pt.p > 0 && pt.t > 0)
        }
        if (!cancelled) setHistory(next)
      } catch {
        // Keep the last good history; the next interval will retry.
      }
    }
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return history
}
