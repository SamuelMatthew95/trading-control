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
// ~1h of high-resolution (3s) live samples. The old 200-point / 10-minute cap
// made the chart "just move live between minutes" with nothing to zoom out to;
// a 1h tail gives the Robinhood-style LIVE / 1H ranges real data, while the
// realized order curve supplies the longer (1D / 1W / 1M / ALL) history.
const MAX_POINTS = 1200
const STORAGE_KEY = 'codex.equityCurve'
// Keep up to a day of live samples across reloads so the longer ranges survive a
// refresh. Older samples are dropped on restore.
const MAX_AGE_MS = 24 * 60 * 60 * 1000
// Persist on a fixed cadence (decoupled from the 3s sampling) so we don't
// re-serialize the whole window to localStorage on every single sample.
const PERSIST_INTERVAL_MS = 15000

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
 * Restore the persisted equity curve, dropping malformed and stale (> 24h)
 * points and capping to the rolling window. Pure + testable; returns [] on the
 * server or when nothing valid is stored.
 *
 * Unlike the old behaviour, this keeps the recent history even when the newest
 * sample is no longer "current" (the tab was away a while). EquityCurve breaks
 * the rendered line across any large time gap, so restoring the history powers
 * the longer ranges without drawing a fabricated sloped segment across the gap.
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
 * Feed to <EquityCurve liveSeries=… /> as the live mark-to-market tail.
 */
export function useLiveEquitySeries(): EquityPoint[] {
  const livePnl = useLivePnl()
  // Read the freshest P&L inside the interval without re-arming it every tick.
  const livePnlRef = useRef(livePnl)
  livePnlRef.current = livePnl
  // Start empty so the server and first client render match (no SSR mismatch);
  // the persisted curve is restored in the mount effect below.
  const [series, setSeries] = useState<EquityPoint[]>([])
  // Latest series for the throttled persister to read without re-arming.
  const seriesRef = useRef(series)
  seriesRef.current = series

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

  // Persist on a fixed cadence (not on every 3s sample) so a reload restores the
  // recent curve instead of resetting to a dot, without thrashing localStorage.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const persist = () => {
      if (seriesRef.current.length === 0) return
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seriesRef.current))
      } catch {
        // Best-effort: ignore quota / serialization errors.
      }
    }
    const id = setInterval(persist, PERSIST_INTERVAL_MS)
    return () => {
      clearInterval(id)
      persist() // flush the latest window on unmount (e.g. SPA navigation)
    }
  }, [])

  return series
}
