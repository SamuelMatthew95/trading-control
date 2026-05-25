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

interface LocalInferenceData {
  lm_studio_enabled: boolean
  lm_studio_healthy: boolean
  local_model: string | null
  local_fallback_count: number
  last_local_error: string | null
  local_latency_ms: number | null
  reachable: boolean
  remote_localhost_mismatch: boolean
  base_url_host: string | null
  available_models: string[] | null
  llm_fallback_enabled: boolean
}

interface LLMHealthData extends LocalInferenceData {
  last_error?: {
    kind: string | null
    message: string | null
    at: string | null
  }

  /** ISO timestamp of the last successful LLM call, from durable Redis storage. */
  last_success_at?: string | null

  status: LLMStatus
  /** Configured cloud fallback provider (gemini / groq / anthropic / openai) */
  provider: string
  /** The provider actually serving requests: "lmstudio" when local is healthy, else provider */
  active_provider: string
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

function LocalInferenceStrip({ data }: { data: LocalInferenceData }) {
  if (!data.lm_studio_enabled) return null

  const healthy = data.lm_studio_healthy
  const dotColor = healthy ? 'bg-emerald-500' : 'bg-slate-400'
  const labelColor = healthy
    ? 'text-emerald-600 dark:text-emerald-500'
    : 'text-slate-500 dark:text-slate-400'

  return (
    <div className="mb-3 rounded-lg border border-indigo-300/30 bg-indigo-500/5 px-3 py-2 text-xs">
      <div className="mb-1.5 flex items-center justify-between">
        <span className={LABEL}>Local GPU / LM Studio</span>
        <span className="flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
          <span className={`text-xs font-semibold ${labelColor}`}>
            {healthy ? 'Active' : 'Offline'}
          </span>
        </span>
      </div>

      {/* Remote-to-localhost mismatch warning */}
      {data.remote_localhost_mismatch && (
        <div className="mb-2 rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1.5 text-amber-700 dark:text-amber-400">
          <span className="font-semibold">Remote backend cannot reach localhost.</span>
          <span className="ml-1">
            Use Tailscale, a public tunnel, or run the backend locally.
          </span>
          {data.base_url_host && (
            <span className={`${MUTED} ml-1`}>
              (host: <span className="font-mono">{data.base_url_host}</span>)
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {data.local_model && (
          <span className={`${MUTED} col-span-2 truncate`}>
            Model: <span className="font-mono">{data.local_model}</span>
          </span>
        )}
        {data.base_url_host && !data.remote_localhost_mismatch && (
          <span className={`${MUTED} col-span-2`}>
            Host: <span className="font-mono">{data.base_url_host}</span>
          </span>
        )}
        {data.local_latency_ms != null && (
          <span className={MUTED}>
            Latency: <span className={VALUE}>{data.local_latency_ms}ms</span>
          </span>
        )}
        <span className={MUTED}>
          Fallbacks:{' '}
          <span
            className={
              data.local_fallback_count > 0
                ? 'font-semibold text-amber-600 dark:text-amber-400'
                : VALUE
            }
          >
            {data.local_fallback_count}
          </span>
        </span>
        {!data.llm_fallback_enabled && (
          <span className={`${MUTED} col-span-2`}>
            Fallback: <span className="font-mono text-slate-500 dark:text-slate-400">disabled</span>
          </span>
        )}
        {data.last_local_error && !data.remote_localhost_mismatch && (
          <span className={`${MUTED} col-span-2`}>
            Error:{' '}
            <span className="font-mono text-rose-500 dark:text-rose-400">
              {data.last_local_error}
            </span>
          </span>
        )}
        {data.available_models && data.available_models.length > 0 && (
          <span className={`${MUTED} col-span-2 truncate`}>
            Loaded: <span className="font-mono">{data.available_models.join(', ')}</span>
          </span>
        )}
      </div>
    </div>
  )
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.round(diffMs / 60_000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHrs = Math.floor(diffMin / 60)
  if (diffHrs < 24) return `${diffHrs}h ${diffMin % 60}m ago`
  return `${Math.floor(diffHrs / 24)}d ago`
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
    const id = setInterval(poll, 5000)
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
          Provider: <span className={VALUE}>{data.active_provider}</span>
        </span>

        <span className={MUTED}>
          Success Rate:{' '}
          <span className={successRateColor(data.success_rate_pct)}>
            {Number(data.success_rate_pct ?? 0).toFixed(0)}%
          </span>{' '}
          <span className={MUTED}>
            ({data.success_count}/{data.total_in_window} last {windowMin}m)
          </span>
        </span>

        <span className={MUTED}>
          Avg Latency:{' '}
          <span className={VALUE}>
            {(data.avg_latency_ms ?? 0) > 0 ? `${Number(data.avg_latency_ms).toFixed(0)}ms` : '--'}
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

        {data.total_in_window === 0 && data.last_success_at && (
          <span className={`${MUTED} col-span-2 italic`}>
            No calls in window — last:{' '}
            <span className={VALUE}>{timeAgo(data.last_success_at)}</span>
          </span>
        )}
      </div>

      <LocalInferenceStrip data={data} />

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
