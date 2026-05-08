/**
 * Shared dashboard view-model types — what the dashboard COMPONENTS see,
 * after normalization. These are not necessarily the same as raw API shapes
 * (see `lib/types/api.ts` for those).
 */

import type { AgentStatus } from '@/lib/state'

export interface AgentSummary {
  name: string
  realtimeCount: number
  persistedCount: number
  lastSeen: Date | null
  status: AgentStatus
  tier: 'active' | 'challenger' | 'inactive'
  source: 'realtime' | 'persisted' | 'hybrid'
}

export interface PipelineStageView {
  key: string
  label: string
  count: number
  lastRun: Date | null
  status: 'Active' | 'Idle' | 'Error'
}

export interface WiringFreshness {
  heartbeatAgeMs: number | null
  instanceAgeMs: number | null
  logAgeMs: number | null
}

export interface DashboardSummaryView {
  dailyPnlNumeric: number
  winRate: number | null
  activePositions: number
  dailyChange: number | null
  hasOrders: boolean
  hasClosedTrades: boolean
}

export interface LearningSummaryView {
  tradesEvaluated: number
  reflectionsCompleted: number
  icValuesUpdated: number
  strategiesTested: number
  bestDay: [string, number] | null
  worstDay: [string, number] | null
}
