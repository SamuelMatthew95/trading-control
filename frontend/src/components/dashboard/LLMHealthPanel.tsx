'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/apiClient'

// Mirrors api/constants.py LLMCallResult StrEnum
const LLMCallResult = {
  SUCCESS: 'success',
  RATE_LIMITED: 'rate_limited',
  TIMEOUT: 'timeout',
  ERROR: 'error',
} as const
type LLMCallResult = (typeof LLMCallResult)[keyof typeof LLMCallResult]

// Mirrors api/routes/llm_health.py _llm_status values
const LLMStatus = {
  LIVE: 'live',
  DEGRADED: 'degraded',
  DOWN: 'down',
  UNKNOWN: 'unknown',
} as const
type LLMStatus = (typeof LLMStatus)[keyof typeof LLMStatus]

interface CallRecord {
  result: LLMCallResult
  latency_ms: number | null
}

interface LLMHealthData {
  status: LLMStatus
  provider: string
  model: string
  timestamp: string
  window_seconds: number
  total_in_window: number
  success_count: number
  success_rate_pct: number
  avg_latency_ms: number
  rate_limited_count: number
  timeout_count: number
  error_count: number
  total_calls_lifetime: number
  daily_calls: number
  recent_results: CallRecord[]
}

const STATUS_DOT_COLOR: Record<LLMStatus, string> = {
  [LLMStatus.LIVE]: 'bg-emerald-500',
  [LLMStatus.DEGRADED]: 'bg-amber-400',
  [LLMStatus.DOWN]: 'bg-rose-500',
  [LLMStatus.UNKNOWN]: 'bg-slate-400',
}
const STATUS_TEXT_COLOR: Record<LLMStatus, string> = {
  [LLMStatus.LIVE]: 'text-emerald-500',
  [LLMStatus.DEGRADED]: 'text-amber-400',
  [LLMStatus.DOWN]: 'text-rose-500',
  [LLMStatus.UNKNOWN]: 'text-slate-400',
}
const STATUS_LABEL: Record<LLMStatus, string> = {
  [LLMStatus.LIVE]: 'Live',
  [LLMStatus.DEGRADED]: 'Degraded',
  [LLMStatus.DOWN]: 'Down',
  [LLMStatus.UNKNOWN]: 'Unknown',
}

function StatusDot({ status }: { status: LLMStatus }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${STATUS_DOT_COLOR[status]}`} />
      <span className={STATUS_TEXT_COLOR[status]}>{STATUS_LABEL[status]}</span>
    </span>
  )
}

function CallDot({ call }: { call: CallRecord }) {
  if (call.result === LLMCallResult.SUCCESS) {
    return (
      <span
        title={`Success — ${call.latency_ms?.toFixed(0) ?? '?'}ms`}
        className="flex items-center gap-0.5 rounded bg-emerald-500/10 px-1 py-0.5 text-[10px] font-mono text-emerald-500"
      >
        ✅ {call.latency_ms?.toFixed(0) ?? '?'}ms
      </span>
    )
  }
  if (call.result === LLMCallResult.RATE_LIMITED) {
    return (
      <span
        title="Rate limited"
        className="rounded bg-amber-400/10 px-1 py-0.5 text-[10px] font-mono text-amber-400"
      >
        ⚠️ RL
      </span>
    )
  }
  if (call.result === LLMCallResult.TIMEOUT) {
    return (
      <span
        title="Timeout"
        className="rounded bg-rose-500/10 px-1 py-0.5 text-[10px] font-mono text-rose-500"
      >
        ❌ TO
      </span>
    )
  }
  return (
    <span
      title="Error"
      className="rounded bg-slate-500/10 px-1 py-0.5 text-[10px] font-mono text-slate-400"
    >
      ❌ ERR
    </span>
  )
}

export function LLMHealthPanel({ isDark }: { isDark?: boolean }) {
  const [data, setData] = useState<LLMHealthData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const result = await apiFetch<LLMHealthData>('/llm/health')
        if (!cancelled) {
          setData(result)
          setError(null)
        }
      } catch {
        if (!cancelled) setError('Unavailable')
      }
    }

    poll()
    const id = setInterval(poll, 5000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const card = isDark
    ? 'border-slate-700 bg-slate-900/80 text-slate-100'
    : 'border-slate-200 bg-white text-slate-900'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const label = 'text-xs font-semibold uppercase tracking-widest font-sans ' + (isDark ? 'text-slate-400' : 'text-slate-500')

  if (error) {
    return (
      <div className={`rounded-xl border p-4 ${card}`}>
        <p className={label}>LLM Health</p>
        <p className={`mt-2 text-sm ${muted}`}>Metrics unavailable</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className={`rounded-xl border p-4 ${card}`}>
        <p className={label}>LLM Health</p>
        <div className="mt-2 space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          ))}
        </div>
      </div>
    )
  }

  const windowMin = Math.round(data.window_seconds / 60)

  return (
    <div className={`rounded-xl border p-4 ${card}`}>
      <div className="mb-3 flex items-center justify-between">
        <p className={label}>LLM Health</p>
        <StatusDot status={data.status} />
      </div>

      <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <span className={muted}>
          Model: <span className="font-mono text-slate-700 dark:text-slate-300">{data.model}</span>
        </span>
        <span className={muted}>
          Provider: <span className="font-mono text-slate-700 dark:text-slate-300">{data.provider}</span>
        </span>
        <span className={muted}>
          Success Rate:{' '}
          <span
            className={
              data.success_rate_pct >= 80
                ? 'font-semibold text-emerald-500'
                : data.success_rate_pct >= 50
                  ? 'font-semibold text-amber-400'
                  : 'font-semibold text-rose-500'
            }
          >
            {data.success_rate_pct.toFixed(0)}%
          </span>{' '}
          <span className={muted}>
            ({data.success_count}/{data.total_in_window} last {windowMin}m)
          </span>
        </span>
        <span className={muted}>
          Avg Latency:{' '}
          <span className="font-mono text-slate-700 dark:text-slate-300">
            {data.avg_latency_ms > 0 ? `${data.avg_latency_ms.toFixed(0)}ms` : '--'}
          </span>
        </span>
        <span className={muted}>
          Rate Limited:{' '}
          <span className={data.rate_limited_count > 0 ? 'font-semibold text-amber-400' : 'text-slate-700 dark:text-slate-300'}>
            {data.rate_limited_count}
          </span>{' '}
          <span className={muted}>(last {windowMin}m)</span>
        </span>
        <span className={muted}>
          Timeouts:{' '}
          <span className={data.timeout_count > 0 ? 'font-semibold text-rose-500' : 'text-slate-700 dark:text-slate-300'}>
            {data.timeout_count}
          </span>{' '}
          <span className={muted}>(last {windowMin}m)</span>
        </span>
        <span className={muted}>
          Daily Calls:{' '}
          <span className="font-mono text-slate-700 dark:text-slate-300">{data.daily_calls}</span>
        </span>
        <span className={muted}>
          Lifetime:{' '}
          <span className="font-mono text-slate-700 dark:text-slate-300">{data.total_calls_lifetime}</span>
        </span>
      </div>

      {data.recent_results.length > 0 && (
        <div>
          <p className={`mb-1.5 text-[10px] font-semibold uppercase tracking-widest ${muted}`}>
            Last {data.recent_results.length} calls
          </p>
          <div className="flex flex-wrap gap-1">
            {data.recent_results.map((call, i) => (
              <CallDot key={i} call={call} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
