'use client'

import { TONE_DOT, TONE_TEXT, type Tone } from '@/lib/design/sentiment'
import { cardClass, monoValueClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { formatTimeAgo } from '@/lib/formatters'
import { Skeleton } from '@/components/ui/loading'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import {
  LLMCallResult,
  LLMStatus,
  useLlmHealth,
  type CallRecord,
  type LocalInferenceData,
} from '@/lib/llm-health'

const COPY = UI_COPY.llmHealth

// LLM health status → semantic Tone (colours resolve through the design tokens).
const LLM_TONE: Record<LLMStatus, Tone> = {
  [LLMStatus.LIVE]: 'success',
  [LLMStatus.DEGRADED]: 'warning',
  [LLMStatus.DOWN]: 'danger',
  [LLMStatus.UNKNOWN]: 'neutral',
}
const STATUS_LABEL: Record<LLMStatus, string> = {
  [LLMStatus.LIVE]: COPY.statusLive,
  [LLMStatus.DEGRADED]: COPY.statusDegraded,
  [LLMStatus.DOWN]: COPY.statusDown,
  [LLMStatus.UNKNOWN]: COPY.statusUnknown,
}

function StatusDot({ status }: { status: LLMStatus }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${TONE_DOT[LLM_TONE[status]]}`} />
      <span className={`text-xs font-semibold ${TONE_TEXT[LLM_TONE[status]]}`}>
        {STATUS_LABEL[status]}
      </span>
    </span>
  )
}

function CallDot({ call }: { call: CallRecord }) {
  if (call.result === LLMCallResult.SUCCESS) {
    return (
      <span
        title={`${COPY.callSuccess} — ${call.latency_ms?.toFixed(0) ?? '?'}ms`}
        className="flex items-center gap-0.5 rounded bg-success/10 px-1 py-0.5 font-mono text-3xs text-success"
      >
        ✓ {call.latency_ms?.toFixed(0) ?? '?'}ms
      </span>
    )
  }
  if (call.result === LLMCallResult.RATE_LIMITED) {
    return (
      <span
        title={COPY.callRateLimited}
        className="rounded bg-warning/10 px-1 py-0.5 font-mono text-3xs text-warning"
      >
        {COPY.callRateLimitedAbbr}
      </span>
    )
  }
  if (call.result === LLMCallResult.TIMEOUT) {
    return (
      <span
        title={COPY.callTimeout}
        className="rounded bg-danger/10 px-1 py-0.5 font-mono text-3xs text-danger"
      >
        {COPY.callTimeoutAbbr}
      </span>
    )
  }
  return (
    <span
      title={COPY.callError}
      className="rounded bg-muted-foreground/10 px-1 py-0.5 font-mono text-3xs text-muted-foreground"
    >
      {COPY.callErrorAbbr}
    </span>
  )
}

// Shared dashboard recipes (single source in lib/dashboard-styles).
const CARD = cardClass
const MUTED = mutedClass
const LABEL = sectionTitleClass
const VALUE = monoValueClass

function successRateColor(pct: number): string {
  if (pct >= 80) return `font-semibold ${TONE_TEXT.success}`
  if (pct >= 50) return `font-semibold ${TONE_TEXT.warning}`
  return `font-semibold ${TONE_TEXT.danger}`
}

function LocalInferenceStrip({ data }: { data: LocalInferenceData }) {
  if (!data.lm_studio_enabled) return null

  const healthy = data.lm_studio_healthy
  const dotColor = healthy ? TONE_DOT.success : TONE_DOT.neutral
  const labelColor = healthy ? TONE_TEXT.success : 'text-muted-foreground'

  return (
    <div className="mb-3 rounded-lg border border-brand/30 bg-brand/5 px-3 py-2 text-xs">
      <div className="mb-1.5 flex items-center justify-between">
        <span className={LABEL}>{COPY.localStripTitle}</span>
        <span className="flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
          <span className={`text-xs font-semibold ${labelColor}`}>
            {healthy ? COPY.localActive : COPY.localOffline}
          </span>
        </span>
      </div>

      {/* Remote-to-localhost mismatch warning */}
      {data.remote_localhost_mismatch && (
        <div className="mb-2 rounded border border-warning/40 bg-warning/10 px-2 py-1.5 text-warning">
          <span className="font-semibold">{COPY.mismatchTitle}</span>
          <span className="ml-1">{COPY.mismatchHint}</span>
          {data.base_url_host && (
            <span className={`${MUTED} ml-1`}>
              ({COPY.host} <span className="font-mono">{data.base_url_host}</span>)
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {data.local_model && (
          <span className={`${MUTED} col-span-2 truncate`}>
            {COPY.model} <span className="font-mono">{data.local_model}</span>
          </span>
        )}
        {data.base_url_host && !data.remote_localhost_mismatch && (
          <span className={`${MUTED} col-span-2`}>
            {COPY.hostLabel} <span className="font-mono">{data.base_url_host}</span>
          </span>
        )}
        {data.local_latency_ms != null && (
          <span className={MUTED}>
            {COPY.latency} <span className={VALUE}>{data.local_latency_ms}ms</span>
          </span>
        )}
        <span className={MUTED}>
          {COPY.fallbacks}{' '}
          <span className={data.local_fallback_count > 0 ? 'font-semibold text-warning' : VALUE}>
            {data.local_fallback_count}
          </span>
        </span>
        {!data.llm_fallback_enabled && (
          <span className={`${MUTED} col-span-2`}>
            {COPY.fallback} <span className="font-mono text-muted-foreground">{COPY.disabled}</span>
          </span>
        )}
        {data.last_local_error && !data.remote_localhost_mismatch && (
          <span className={`${MUTED} col-span-2`}>
            {COPY.errorLabel} <span className="font-mono text-danger">{data.last_local_error}</span>
          </span>
        )}
        {data.available_models && data.available_models.length > 0 && (
          <span className={`${MUTED} col-span-2 truncate`}>
            {COPY.loaded} <span className="font-mono">{data.available_models.join(', ')}</span>
          </span>
        )}
      </div>
    </div>
  )
}

function DelayValue({ delayMs, gradeAdjusted }: { delayMs: number; gradeAdjusted: boolean }) {
  const color = gradeAdjusted
    ? delayMs >= 1000
      ? `font-semibold ${TONE_TEXT.danger}`
      : `font-semibold ${TONE_TEXT.warning}`
    : VALUE
  return (
    <span className={color}>
      {delayMs}ms{gradeAdjusted ? ' ↑' : ''}
    </span>
  )
}

export function LLMHealthPanel() {
  const { data, error } = useLlmHealth()

  if (error) {
    return (
      <div className={CARD}>
        <p className={LABEL}>{COPY.title}</p>
        <p className={`mt-2 text-sm ${MUTED}`}>{COPY.unavailable}</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className={CARD}>
        <p className={LABEL}>{COPY.title}</p>
        <div className="mt-2 space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-3" />
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
        <p className={LABEL}>{COPY.title}</p>
        <StatusDot status={data.status} />
      </div>

      {/* Primary metrics grid */}
      <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <span className={MUTED}>
          {COPY.model} <span className={VALUE}>{data.model}</span>
        </span>
        <span className={MUTED}>
          {COPY.provider} <span className={VALUE}>{data.active_provider}</span>
        </span>

        <span className={MUTED}>
          {COPY.successRate}{' '}
          <span className={successRateColor(data.success_rate_pct)}>
            {Number(data.success_rate_pct ?? 0).toFixed(0)}%
          </span>{' '}
          <span className={MUTED}>
            ({data.success_count}/{data.total_in_window} {COPY.last} {windowMin}m)
          </span>
        </span>

        <span className={MUTED}>
          {COPY.avgLatency}{' '}
          <span className={VALUE}>
            {(data.avg_latency_ms ?? 0) > 0 ? `${Number(data.avg_latency_ms).toFixed(0)}ms` : NO_DATA}
          </span>
        </span>

        <span className={MUTED}>
          {COPY.rateLimited}{' '}
          <span className={data.rate_limited_count > 0 ? 'font-semibold text-warning' : VALUE}>
            {data.rate_limited_count}
          </span>{' '}
          <span className={MUTED}>({COPY.last} {windowMin}m)</span>
        </span>

        <span className={MUTED}>
          {COPY.timeouts}{' '}
          <span className={data.timeout_count > 0 ? 'font-semibold text-danger' : VALUE}>
            {data.timeout_count}
          </span>{' '}
          <span className={MUTED}>({COPY.last} {windowMin}m)</span>
        </span>

        <span className={MUTED}>
          {COPY.dailyCalls} <span className={VALUE}>{data.daily_calls}</span>
        </span>

        <span className={MUTED}>
          {COPY.lifetime} <span className={VALUE}>{data.total_calls_lifetime}</span>
        </span>

        {data.total_in_window === 0 && data.last_success_at && (
          <span className={`${MUTED} col-span-2 italic`}>
            {COPY.noCallsInWindow}{' '}
            <span className={VALUE}>{formatTimeAgo(data.last_success_at)}</span>
          </span>
        )}
      </div>

      <LocalInferenceStrip data={data} />

      {data.last_error?.message && (
        <div className="mb-3 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
          {COPY.lastError} <span className="font-mono">{data.last_error.message}</span>
        </div>
      )}

      {/* GradeAgent call-rate adjustment banner */}
      <div
        className={`mb-3 flex items-center justify-between rounded-lg border px-3 py-2 text-xs ${
          data.grade_adjusted_delay ? 'border-warning/30 bg-warning/5' : 'bg-muted/40'
        }`}
      >
        <span className={MUTED}>
          {COPY.callDelay}{' '}
          <span className={`${MUTED} text-3xs`}>
            ({COPY.gradeAgent} {data.grade_adjusted_delay ? COPY.gradeAdjusted : COPY.gradeDefault})
          </span>
          :
        </span>
        <DelayValue delayMs={data.effective_delay_ms} gradeAdjusted={data.grade_adjusted_delay} />
      </div>

      {/* Recent call history */}
      {data.recent_results && data.recent_results.length > 0 && (
        <div>
          <p className={`mb-1.5 ${LABEL}`}>
            {COPY.lastCallsPrefix} {data.recent_results.length} {COPY.lastCalls}
          </p>
          <div className="flex flex-wrap gap-1">
            {data.recent_results.map((call, i) => (
              <CallDot key={`${i}-${call.result}`} call={call} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
