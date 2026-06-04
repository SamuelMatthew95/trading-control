import { useEffect, useState } from 'react'

import { apiFetch } from '@/lib/apiClient'

// Mirrors api/constants.py LLMCallResult StrEnum
export const LLMCallResult = {
  SUCCESS: 'success',
  RATE_LIMITED: 'rate_limited',
  TIMEOUT: 'timeout',
  ERROR: 'error',
} as const
export type LLMCallResult = (typeof LLMCallResult)[keyof typeof LLMCallResult]

// Mirrors api/routes/llm_health.py _llm_status values — the canonical LLM
// status vocabulary. Both the health panel and the page-level degraded banner
// import this so the union lives in exactly one place (frontend design rule:
// never re-declare a status union locally).
export const LLMStatus = {
  LIVE: 'live',
  DEGRADED: 'degraded',
  DOWN: 'down',
  UNKNOWN: 'unknown',
} as const
export type LLMStatus = (typeof LLMStatus)[keyof typeof LLMStatus]

export interface CallRecord {
  result: LLMCallResult
  latency_ms: number | null
}

export interface LocalInferenceData {
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

export interface LLMHealthData extends LocalInferenceData {
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

/** Poll cadence for `/llm/health` — matches the agent heartbeat refresh feel. */
export const LLM_HEALTH_POLL_MS = 5000

/**
 * Poll `/llm/health` on a fixed interval and expose the latest snapshot.
 *
 * Shared by {@link LLMHealthPanel} and the page-level degraded banner so the
 * fetch + status logic is defined once. Returns `data: null` until the first
 * response and `error` when the endpoint is unreachable.
 */
export function useLlmHealth(): { data: LLMHealthData | null; error: string | null } {
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

  return { data, error }
}
