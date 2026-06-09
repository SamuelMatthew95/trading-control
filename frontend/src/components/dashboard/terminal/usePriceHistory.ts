'use client'

import { useEffect, useRef, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { liveStorePrice, previousStorePrice } from './marketData'
import type { PricePoint } from './types'

const SAMPLE_MS = 2000
const MAX_POINTS = 180

/**
 * Accumulate the REAL streamed price for each symbol into a rolling per-symbol
 * series, sampled on an interval. This is the live intraday history the chart
 * and sparklines render — built entirely from the price stream, never synthesised.
 *
 * `symbols` must be a stable reference (module constant) so the sampler isn't
 * torn down and rebuilt on every render.
 */
export function usePriceHistory(symbols: string[]): Record<string, PricePoint[]> {
  const prices = useCodexStore((s) => s.prices)
  const pricesRef = useRef(prices)
  pricesRef.current = prices
  const [history, setHistory] = useState<Record<string, PricePoint[]>>({})

  useEffect(() => {
    const sample = () => {
      const now = Date.now()
      setHistory((prev) => {
        const next: Record<string, PricePoint[]> = { ...prev }
        for (const sym of symbols) {
          const price = liveStorePrice(pricesRef.current, sym)
          if (price == null) continue
          let series = next[sym]
          if (!series) {
            // Seed with the previous-poll price so the first render already has a
            // two-point segment instead of a single dot (both points are real).
            const prevPrice = previousStorePrice(pricesRef.current, sym)
            series = prevPrice != null ? [{ t: now - SAMPLE_MS, p: prevPrice }] : []
          }
          const appended = series.concat({ t: now, p: price })
          next[sym] = appended.length > MAX_POINTS ? appended.slice(appended.length - MAX_POINTS) : appended
        }
        return next
      })
    }
    sample()
    const id = setInterval(sample, SAMPLE_MS)
    return () => clearInterval(id)
  }, [symbols])

  return history
}
