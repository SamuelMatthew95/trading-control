'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { apiFetch } from '@/lib/apiClient'

interface StrategyRow {
  name: string
  return_pct: number
  trade_count: number
  sharpe_ratio: number
  win_rate: number
}

interface BacktestCompareResponse {
  mode: string
  source: string
  symbol: string
  bars: number
  summary: string
  cached: boolean
  generated_at: string
  candidate: string | null
  baseline: string | null
  is_different: boolean
  beats_baseline: boolean
  decision: string
  reason: string
  strategies: StrategyRow[]
}

export function BacktestComparisonPanel() {
  const [data, setData] = useState<BacktestCompareResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const cancelled = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiFetch<BacktestCompareResponse>('/backtest/compare')
      if (!cancelled.current) {
        setData(result)
        setError(null)
      }
    } catch (e) {
      if (!cancelled.current) {
        setError(e instanceof Error ? e.message : 'Failed to load backtest')
      }
    } finally {
      if (!cancelled.current) setLoading(false)
    }
  }, [])

  // Fetch once on mount. The result is cached server-side, so we deliberately do
  // NOT poll on a timer — re-running the backtest repeatedly would hammer the
  // data API and recompute an identical answer. Refresh is on demand only.
  useEffect(() => {
    cancelled.current = false
    void load()
    return () => {
      cancelled.current = true
    }
  }, [load])

  return (
    <div className={CARD}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className={LABEL}>Backtest — Strategy Comparison</p>
        <button type="button" onClick={() => void load()} disabled={loading} className={BTN}>
          {loading ? 'Running…' : 'Refresh'}
        </button>
      </div>
      <p className={`mb-3 ${MUTED}`}>
        Replays the live SignalGenerator decision through the GradeAgent&apos;s scorer — the same
        pipeline the agents run, measured offline.
      </p>

      {error && <p className={MUTED}>Backtest unavailable: {error}</p>}

      {!error && !data && (
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          ))}
        </div>
      )}

      {!error && data && (
        <>
          {data.candidate && (
            <div
              className={`mb-3 rounded-lg border p-2 ${
                data.decision === 'promote' ? PROMOTE_BOX : REJECT_BOX
              }`}
            >
              <p className="text-xs font-semibold text-slate-800 dark:text-slate-100">
                Challenger: {data.candidate} — different {data.is_different ? '✓' : '✗'} · beats
                baseline {data.beats_baseline ? '✓' : '✗'} → {data.decision.toUpperCase()}
              </p>
              <p className={`mt-0.5 ${MUTED}`}>{data.reason}</p>
            </div>
          )}
          <div className="overflow-x-auto rounded-lg border border-slate-300 dark:border-slate-800">
            <table className="w-full text-xs font-mono">
              <thead className="bg-slate-100 dark:bg-slate-800/90">
                <tr className="text-left text-slate-500">
                  <th className="p-2">Strategy</th>
                  <th className="p-2 text-right">Return</th>
                  <th className="p-2 text-right">Trades</th>
                  <th className="p-2 text-right">Sharpe</th>
                  <th className="p-2 text-right">Win</th>
                </tr>
              </thead>
              <tbody>
                {data.strategies.map((s) => (
                  <tr key={s.name} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="p-2 font-semibold text-slate-900 dark:text-slate-100">
                      {s.name}
                    </td>
                    <td className={`p-2 text-right ${s.return_pct >= 0 ? POS : NEG}`}>
                      {s.return_pct >= 0 ? '+' : ''}
                      {s.return_pct.toFixed(2)}%
                    </td>
                    <td className="p-2 text-right text-slate-600 dark:text-slate-300">
                      {Math.round(s.trade_count)}
                    </td>
                    <td className="p-2 text-right text-slate-600 dark:text-slate-300">
                      {s.sharpe_ratio.toFixed(2)}
                    </td>
                    <td className="p-2 text-right text-slate-600 dark:text-slate-300">
                      {(s.win_rate * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.summary && <p className={`mt-3 ${MUTED}`}>{data.summary}</p>}
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
const POS = 'text-emerald-600 dark:text-emerald-400'
const NEG = 'text-rose-600 dark:text-rose-400'
const PROMOTE_BOX =
  'border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40'
const REJECT_BOX = 'border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/40'
const BTN =
  'rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800'
