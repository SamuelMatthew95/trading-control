'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { apiFetch } from '@/lib/apiClient'

interface ThresholdStat {
  threshold: number
  percentile: number
  hit_rate: number
}

interface TimeframeBlock {
  timeframe_bars: number
  sample_size: number
  abs_pct: Record<string, number> // p50 / p90 / p99 / p99.9 / max
  rolling_sigma: Record<string, number> // p50 / p95
  thresholds: ThresholdStat[]
}

interface DistributionResponse {
  mode: string
  source: string
  symbol: string
  bars: number
  cached: boolean
  timeframes: TimeframeBlock[]
}

// A fixed % trigger is meaningful only relative to how big moves actually get on
// the timeframe. The deeper into the tail it sits, the rarer (and more likely
// "unreachable") it is — flag that visually.
function pctTone(percentile: number): string {
  if (percentile >= 99) return 'text-rose-600 dark:text-rose-400'
  if (percentile >= 95) return 'text-amber-600 dark:text-amber-400'
  return 'text-slate-700 dark:text-slate-200'
}

function fmtPct(v: number | undefined): string {
  return v === undefined ? '—' : `${v.toFixed(2)}%`
}

function fmtFreq(hitRate: number): string {
  if (hitRate <= 0) return 'never'
  if (hitRate >= 0.01) return `${(hitRate * 100).toFixed(1)}%/bar`
  return `~1 in ${Math.round(1 / hitRate)} bars`
}

function tfLabel(bars: number): string {
  return bars === 1 ? '1-bar' : `${bars}-bar`
}

export function DistributionPanel() {
  const [data, setData] = useState<DistributionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const cancelled = useRef(false)

  const load = useCallback(async (force = false) => {
    setLoading(true)
    try {
      const path = force ? '/backtest/distribution?force=true' : '/backtest/distribution'
      const result = await apiFetch<DistributionResponse>(path)
      if (!cancelled.current) {
        setData(result)
        setError(null)
      }
    } catch (e) {
      if (!cancelled.current) {
        setError(e instanceof Error ? e.message : 'Failed to load distribution')
      }
    } finally {
      if (!cancelled.current) setLoading(false)
    }
  }, [])

  // Fetch once on mount; the result is cached server-side (like /compare), so we
  // don't poll — Run now forces a fresh recompute.
  useEffect(() => {
    cancelled.current = false
    void load()
    return () => {
      cancelled.current = true
    }
  }, [load])

  // Threshold columns are derived from the data so they track the live triggers.
  const thresholds = data?.timeframes[0]?.thresholds ?? []

  return (
    <div className={CARD}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className={LABEL}>Move Distribution — Threshold Calibration</p>
        <button type="button" onClick={() => void load(true)} disabled={loading} className={BTN}>
          {loading ? 'Running…' : 'Run now'}
        </button>
      </div>
      <p className={`mb-3 ${MUTED}`}>
        Where the live signal triggers fall in the distribution of actual moves, per timeframe. A
        trigger deep in the tail (high percentile) almost never fires — calibration as evidence, not
        a guess.
      </p>

      {error && <p className={MUTED}>Distribution unavailable: {error}</p>}

      {!error && !data && (
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          ))}
        </div>
      )}

      {!error && data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-slate-300 dark:border-slate-800">
            <table className="w-full text-xs font-mono">
              <thead className="bg-slate-100 dark:bg-slate-800/90">
                <tr className="text-left text-slate-500">
                  <th className="p-2">Timeframe</th>
                  <th className="p-2 text-right">|move| p50</th>
                  <th className="p-2 text-right">p90</th>
                  <th className="p-2 text-right">p99</th>
                  {thresholds.map((t) => (
                    <th key={t.threshold} className="p-2 text-right">
                      {t.threshold.toFixed(1)}% trigger
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.timeframes.map((tf) => (
                  <tr
                    key={tf.timeframe_bars}
                    className="border-t border-slate-200 dark:border-slate-800"
                  >
                    <td className="p-2 font-semibold text-slate-900 dark:text-slate-100">
                      {tfLabel(tf.timeframe_bars)}
                    </td>
                    <td className="p-2 text-right text-slate-600 dark:text-slate-300">
                      {fmtPct(tf.abs_pct.p50)}
                    </td>
                    <td className="p-2 text-right text-slate-600 dark:text-slate-300">
                      {fmtPct(tf.abs_pct.p90)}
                    </td>
                    <td className="p-2 text-right text-slate-600 dark:text-slate-300">
                      {fmtPct(tf.abs_pct.p99)}
                    </td>
                    {tf.thresholds.map((t) => (
                      <td key={t.threshold} className="p-2 text-right">
                        <span className={`font-semibold ${pctTone(t.percentile)}`}>
                          p{t.percentile.toFixed(1)}
                        </span>
                        <span className="block text-[10px] text-slate-400">
                          {fmtFreq(t.hit_rate)}
                        </span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={`mt-3 ${MUTED}`}>
            A fixed % trigger is a different event on every timeframe — that&apos;s why
            volatility-normalized triggering (move &gt; k·σ) is the durable fix.
          </p>
          <p className={`mt-2 ${FOOT}`}>
            source: {data.source} · {data.symbol} · {data.bars} bars
            {data.cached ? ' · cached' : ''}
          </p>
        </>
      )}
    </div>
  )
}

const CARD =
  'rounded-xl border border-slate-300 bg-white p-4 dark:border-slate-800 dark:bg-slate-900'
const LABEL =
  'text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400'
const MUTED = 'text-xs text-slate-500 dark:text-slate-400'
const FOOT = 'text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500'
const BTN =
  'rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800'
