'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/apiClient'
import { LLM_HEALTH_POLL_MS } from '@/lib/constants/polling'

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
  last_error?: {
    kind: string | null
    message: string | null
    at: string | null
  }

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
  effective_delay_ms: number
  grade_adjusted_delay: boolean
  recent_results: CallRecord[]
}

const STATUS_DOT_COLOR: Record<LLMStatus, string> = {
  [LLMStatus.LIVE]: 'bg-emerald-500',
  [LLMStatus.DEGRADED]: 'bg-amber-400',
  [LLMStatus.DOWN]: 'bg-rose-500',
  [LLMStatus.UNKNOWN]: 'bg-slate-400',
}
const STATUS_TEXT_COLOR: Record<LLMStatus, string> = {
  [LLMStatus.LIVE]: 'text-emerald-600 dark:text-emerald-500',
  [LLMStatus.DEGRADED]: 'text-amber-600 dark:text-amber-400',
  [LLMStatus.DOWN]: 'text-rose-600 dark:text-rose-500',
  [LLMStatus.UNKNOWN]: 'text-slate-500 dark:text-slate-400',
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
      <span className={`text-xs font-semibold ${STATUS_TEXT_COLOR[status]}`}>
        {STATUS_LABEL[status]}
      </span>
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
        ✓ {call.latency_ms?.toFixed(0) ?? '?'}ms
      </span>
    )
  }
  if (call.result === LLMCallResult.RATE_LIMITED) {
    return (
      <span
        title="Rate limited"
        className="rounded bg-amber-50 px-1 py-0.5 text-[10px] font-mono text-amber-700 dark:bg-amber-400/10 dark:text-amber-400"
      >
        RL
      </span>
    )
  }
  if (call.result === LLMCallResult.TIMEOUT) {
    return (
      <span
        title="Timeout"
        className="rounded bg-rose-500/10 px-1 py-0.5 text-[10px] font-mono text-rose-500"
      >
        TO
      </span>
    )
  }
  return (
    <span
      title="Error"
      className="rounded bg-slate-200 px-1 py-0.5 text-[10px] font-mono text-slate-600 dark:bg-slate-500/10 dark:text-slate-400"
    >
      ERR
    </span>
  )
}

const CARD = 'rounded-xl border border-slate-300 bg-white p-4 text-slate-900 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100'
const MUTED = 'text-xs text-slate-500 dark:text-slate-400'
const LABEL = 'text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400'
const VALUE = 'font-mono text-slate-700 dark:text-slate-300'

function successRateColor(pct: number): string {
  if (pct >= 80) return 'font-semibold text-emerald-600 dark:text-emerald-500'
  if (pct >= 50) return 'font-semibold text-amber-600 dark:text-amber-400'
  return 'font-semibold text-rose-600 dark:text-rose-500'
}

function DelayValue({ delayMs, gradeAdjusted }: { delayMs: number; gradeAdjusted: boolean }) {
  const color = gradeAdjusted
    ? delayMs >= 1000
      ? 'font-semibold text-rose-600 dark:text-rose-500'
      : 'font-semibold text-amber-600 dark:text-amber-400'
    : VALUE
  return (
    <span className={color}>
      {delayMs}ms{gradeAdjusted ? ' ↑' : ''}
    </span>
  )
}

export function LLMHealthPanel() {
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
    const id = setInterval(poll, LLM_HEALTH_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  if (error) {
    return (
      <div className={CARD}>
        <p className={LABEL}>LLM Health</p>
        <p className={`mt-2 text-sm ${MUTED}`}>Metrics unavailable</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className={CARD}>
        <p className={LABEL}>LLM Health</p>
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
    <div className={CARD}>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <p className={LABEL}>LLM Health</p>
        <StatusDot status={data.status} />
      </div>

      {/* Primary metrics grid */}
      <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <span className={MUTED}>
          Model: <span className={VALUE}>{data.model}</span>
        </span>
        <span className={MUTED}>
          Provider: <span className={VALUE}>{data.provider}</span>
        </span>

        <span className={MUTED}>
          Success Rate:{' '}
          <span className={successRateColor(data.success_rate_pct)}>
            {data.success_rate_pct.toFixed(0)}%
          </span>{' '}
          <span className={MUTED}>
            ({data.success_count}/{data.total_in_window} last {windowMin}m)
          </span>
        </span>

        <span className={MUTED}>
          Avg Latency:{' '}
          <span className={VALUE}>
            {data.avg_latency_ms > 0 ? `${data.avg_latency_ms.toFixed(0)}ms` : '--'}
          </span>
        </span>

        <span className={MUTED}>
          Rate Limited:{' '}
          <span className={data.rate_limited_count > 0 ? 'font-semibold text-amber-600 dark:text-amber-400' : VALUE}>
            {data.rate_limited_count}
          </span>{' '}
          <span className={MUTED}>(last {windowMin}m)</span>
        </span>

        <span className={MUTED}>
          Timeouts:{' '}
          <span className={data.timeout_count > 0 ? 'font-semibold text-rose-500' : VALUE}>
            {data.timeout_count}
          </span>{' '}
          <span className={MUTED}>(last {windowMin}m)</span>
        </span>

        <span className={MUTED}>
          Daily Calls: <span className={VALUE}>{data.daily_calls}</span>
        </span>

        <span className={MUTED}>
          Lifetime: <span className={VALUE}>{data.total_calls_lifetime}</span>
        </span>
      </div>

      {data.last_error?.message && (
        <div className="mb-3 rounded-lg border border-rose-300/40 bg-rose-500/5 px-3 py-2 text-xs text-rose-600 dark:text-rose-400">
          Last error: <span className="font-mono">{data.last_error.message}</span>
        </div>
      )}

      {/* GradeAgent call-rate adjustment banner */}
      <div
        className={`mb-3 flex items-center justify-between rounded-lg border px-3 py-2 text-xs ${
          data.grade_adjusted_delay
            ? 'border-amber-400/30 bg-amber-400/5'
            : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/40'
        }`}
      >
        <span className={MUTED}>
          Call Delay{' '}
          <span className={`${MUTED} text-[10px]`}>
            (GradeAgent {data.grade_adjusted_delay ? 'adjusted' : 'default'})
          </span>
          :
        </span>
        <DelayValue delayMs={data.effective_delay_ms} gradeAdjusted={data.grade_adjusted_delay} />
      </div>

      {/* Recent call history */}
      {data.recent_results.length > 0 && (
        <div>
          <p className={`mb-1.5 text-[10px] font-semibold uppercase tracking-widest ${MUTED}`}>
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
