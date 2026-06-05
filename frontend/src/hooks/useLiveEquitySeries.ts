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
const STORAGE_KEY = 'codex.equityCurve'
// Drop samples older than this when restoring after a reload, so a curve from a
// previous session/day doesn't graft a misleading jump onto the current one.
const MAX_AGE_MS = 60 * 60 * 1000

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
 * Restore the persisted equity curve, dropping malformed and stale (> 1h)
 * points and capping to the rolling window. Pure + testable; returns [] on the
 * server or when nothing valid is stored.
 */
export function loadPersistedEquitySeries(now: number = Date.now()): EquityPoint[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const cutoff = now - MAX_AGE_MS
    return parsed
      .filter(
        (p): p is EquityPoint =>
          !!p &&
          typeof (p as EquityPoint).timestamp === 'number' &&
          typeof (p as EquityPoint).equity === 'number' &&
          (p as EquityPoint).timestamp >= cutoff,
      )
      .slice(-MAX_POINTS)
  } catch {
    return []
  }
}

/**
 * Rolling, real-time equity series sampled from {@link useLivePnl}. Restores the
 * recent curve from localStorage on mount (so a reload doesn't reset it to a
 * single dot) and grows one point per {@link SAMPLE_INTERVAL_MS} while mounted.
 * Feed to <EquityCurve liveSeries=… /> as the fallback when no closed-order
 * curve exists.
 */
export function useLiveEquitySeries(): EquityPoint[] {
  const livePnl = useLivePnl()
  // Read the freshest P&L inside the interval without re-arming it every tick.
  const livePnlRef = useRef(livePnl)
  livePnlRef.current = livePnl
  // Start empty so the server and first client render match (no SSR mismatch);
  // the persisted curve is restored in the mount effect below.
  const [series, setSeries] = useState<EquityPoint[]>([])

  useEffect(() => {
    const restored = loadPersistedEquitySeries()
    if (restored.length > 0) setSeries(restored)
    const sample = () => {
      const current = livePnlRef.current
      if (!current.hasData) return
      setSeries((prev) => appendEquitySample(prev, current.total, Date.now()))
    }
    sample() // seed immediately so a fresh open position renders a point at once
    const id = setInterval(sample, SAMPLE_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  // Persist so a reload restores the recent curve instead of resetting to a dot.
  useEffect(() => {
    if (typeof window === 'undefined' || series.length === 0) return
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(series))
    } catch {
      // Best-effort: ignore quota / serialization errors.
    }
  }, [series])

  return series
}
