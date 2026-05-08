/**
 * Shared API contract types.
 *
 * These shapes are the typed surface between `lib/api/*` and the rest of the
 * app. They mirror the Pydantic schemas on the backend; mismatches here mean
 * the backend has drifted from the frontend contract.
 */

import type {
  AgentLog,
  Order,
  Position,
} from '@/stores/useCodexStore'

export type ApiHealthState = 'pending' | 'ok' | 'error'

export interface ApiError {
  status: number
  statusText: string
  url: string
  message: string
}

export interface DashboardStateResponse {
  orders?: Order[]
  positions?: Position[]
  agent_logs?: AgentLog[]
  notifications?: Array<Record<string, unknown>>
  llm_available?: boolean
  llm_provider?: string
  mode?: string
  daily_change_pct?: number
  /** Server-supplied snapshot timestamp; missing on legacy responses. */
  timestamp?: string
  [key: string]: unknown
}

export interface PersistedStreamCount {
  stream: string
  processed_count: number
  last_processed_at: string | null
}

export interface PersistedHistoryItem {
  id: string
  kind: string
  source?: string | null
  trace_id?: string | null
  created_at: string | null
}

export interface EventsHistoryResponse {
  stream_counts?: PersistedStreamCount[]
  persisted_events?: PersistedHistoryItem[]
  persisted_logs?: PersistedHistoryItem[]
}

export interface KillSwitchResponse {
  active?: boolean
}

export interface TraceData {
  trace_id: string
  agent_runs: Array<Record<string, unknown>>
  agent_logs: Array<Record<string, unknown>>
  agent_grades: Array<Record<string, unknown>>
}
