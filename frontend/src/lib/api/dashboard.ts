/**
 * Dashboard API endpoints — typed wrappers around `apiFetch`.
 *
 * All callers in `app/`, `components/`, and `hooks/` MUST use this module
 * instead of raw `fetch(api(...))`. The wrappers add typing, normalize empty
 * responses, and route errors through one consistent path.
 */

import { API_ENDPOINTS, api, apiFetch } from '@/lib/apiClient'
import type { AgentInstance, TradeFeedItem } from '@/stores/useCodexStore'
import type {
  DashboardStateResponse,
  EventsHistoryResponse,
  KillSwitchResponse,
  TraceData,
} from '@/lib/types'

export async function getDashboardState(): Promise<DashboardStateResponse> {
  return apiFetch<DashboardStateResponse>('/dashboard/state')
}

export async function getKillSwitch(): Promise<KillSwitchResponse> {
  return apiFetch<KillSwitchResponse>('/dashboard/kill-switch')
}

export async function setKillSwitch(active: boolean): Promise<KillSwitchResponse> {
  return apiFetch<KillSwitchResponse>('/dashboard/kill-switch', {
    method: 'POST',
    body: JSON.stringify({ active }),
  })
}

export interface TradeFeedResponse {
  trades?: TradeFeedItem[]
}

export async function getTradeFeed(): Promise<TradeFeedResponse> {
  return apiFetch<TradeFeedResponse>(API_ENDPOINTS.DASHBOARD_TRADE_FEED)
}

export interface PerformanceTrendsResponse {
  summary?: {
    total_pnl: number
    total_trades: number
    win_rate: number
    avg_win: number
    avg_loss: number
    best_trade: number
    worst_trade: number
  }
}

export async function getPerformanceTrends(): Promise<PerformanceTrendsResponse> {
  return apiFetch<PerformanceTrendsResponse>(API_ENDPOINTS.DASHBOARD_PERFORMANCE_TRENDS)
}

export interface AgentInstancesResponse {
  instances?: AgentInstance[]
}

export async function getAgentInstances(): Promise<AgentInstancesResponse> {
  return apiFetch<AgentInstancesResponse>(API_ENDPOINTS.DASHBOARD_AGENT_INSTANCES)
}

export async function getEventsHistory(): Promise<EventsHistoryResponse> {
  return apiFetch<EventsHistoryResponse>(API_ENDPOINTS.EVENTS_HISTORY)
}

export async function getTrace(traceId: string): Promise<TraceData> {
  return apiFetch<TraceData>(`/dashboard/trace/${encodeURIComponent(traceId)}`)
}

/** Used to verify the API base URL is correctly normalized. */
export function getDashboardStateUrl(): string {
  return api('/dashboard/state')
}
