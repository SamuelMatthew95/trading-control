'use client'

import { useEffect, useRef, useState } from 'react'
import { useLivePnl } from '@/hooks/useLivePnl'
import type { EquityPoint } from '@/components/dashboard/EquityCurve'

// A real-time equity curve needs time-series samples, but in memory mode (or
// before any trade closes) there are no filled orders to build one from — only
// a live, mark-to-market total P&L that moves with the price stream. So we
// sample that total on a fixed cadence and accumulate a rolling window, turning
// an open position into an actual curve instead of "No equity data yet".
const SAMPLE_INTERVAL_MS = 3000
const MAX_POINTS = 200

/**
 * Append one live-equity sample, pure + testable.
 *
 * `total` is the live total P&L (realized + mark-to-market unrealized). `delta`
 * is the move since the previous sample; the window is capped at `maxPoints`
 * (oldest dropped) so a long-lived tab stays bounded.
 */
export function appendEquitySample(
  prev: EquityPoint[],
  total: number,
  now: number,
  maxPoints: number = MAX_POINTS,
): EquityPoint[] {
  const prevEquity = prev.length > 0 ? prev[prev.length - 1].equity : 0
  const point: EquityPoint = {
    timestamp: now,
    label: '',
    pnl: total,
    delta: total - prevEquity,
    equity: total,
  }
  const next = [...prev, point]
  return next.length > maxPoints ? next.slice(next.length - maxPoints) : next
}

/**
 * Rolling, real-time equity series sampled from {@link useLivePnl}. Empty until
 * there is live P&L data (an order or open position); grows one point per
 * {@link SAMPLE_INTERVAL_MS} while mounted. Feed to <EquityCurve liveSeries=… />
 * as the fallback when no closed-order curve exists.
 */
export function useLiveEquitySeries(): EquityPoint[] {
  const livePnl = useLivePnl()
  // Read the freshest P&L inside the interval without re-arming it every tick.
  const livePnlRef = useRef(livePnl)
  livePnlRef.current = livePnl
  const [series, setSeries] = useState<EquityPoint[]>([])

  useEffect(() => {
    const sample = () => {
      const current = livePnlRef.current
      if (!current.hasData) return
      setSeries((prev) => appendEquitySample(prev, current.total, Date.now()))
    }
    sample() // seed immediately so a fresh open position renders a point at once
    const id = setInterval(sample, SAMPLE_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  return series
}
