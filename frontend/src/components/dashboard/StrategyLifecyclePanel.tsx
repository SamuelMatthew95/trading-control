'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { apiFetch } from '@/lib/apiClient'

interface StrategyRow {
  id: string
  name: string
  version: number
  status: string
}

interface StrategiesResponse {
  mode: string
  strategies: StrategyRow[]
  circuit_breaker_active: boolean
}

// Stage badge colors — green=live, amber=in-flight, sky=backtested, slate=proposed/retired.
const STAGE_STYLE: Record<string, string> = {
  live: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300',
  canary: 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
  shadow: 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
  backtested: 'bg-sky-100 text-sky-700 dark:bg-sky-900/50 dark:text-sky-300',
  proposed: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  retired: 'bg-slate-100 text-slate-400 line-through dark:bg-slate-800 dark:text-slate-500',
}

export function StrategyLifecyclePanel() {
  const [data, setData] = useState<StrategiesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)

  const load = useCallback(async () => {
    try {
      const result = await apiFetch<StrategiesResponse>('/backtest/strategies')
      if (!cancelled.current) {
        setData(result)
        setError(null)
      }
    } catch (e) {
      if (!cancelled.current) {
        setError(e instanceof Error ? e.message : 'Failed to load lifecycle')
      }
    }
  }, [])

  useEffect(() => {
    cancelled.current = false
    void load()
    return () => {
      cancelled.current = true
    }
  }, [load])

  return (
    <div className={CARD}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className={LABEL}>Strategy Lifecycle</p>
        {data?.circuit_breaker_active && (
          <span className="rounded bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-700 dark:bg-rose-900/50 dark:text-rose-300">
            circuit breaker tripped
          </span>
        )}
      </div>

      {error && <p className={MUTED}>Lifecycle unavailable: {error}</p>}

      {!error && !data && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          ))}
        </div>
      )}

      {!error && data && (
        <ul className="space-y-1.5">
          {data.strategies.map((s) => (
            <li key={s.id} className="flex items-center justify-between text-sm">
              <span className="font-mono text-slate-800 dark:text-slate-100">
                {s.name} <span className="text-slate-400">v{s.version}</span>
              </span>
              <span
                className={`rounded px-2 py-0.5 text-xs font-semibold ${
                  STAGE_STYLE[s.status] ?? STAGE_STYLE.proposed
                }`}
              >
                {s.status}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className={`mt-3 ${FOOT}`}>
        proposed → backtested → shadow → canary → live · nothing skips a stage
      </p>
    </div>
  )
}

const CARD =
  'rounded-xl border border-slate-300 bg-white p-4 dark:border-slate-800 dark:bg-slate-900'
const LABEL =
  'text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400'
const MUTED = 'text-xs text-slate-500 dark:text-slate-400'
const FOOT = 'text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500'
