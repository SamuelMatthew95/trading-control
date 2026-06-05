/**
 * Types for the per-agent performance grading API.
 *
 * Mirrors api/services/dashboard/agent_performance.py — each pipeline agent is
 * graded on its own telemetry (liveness, success rate, throughput, latency),
 * earns a letter grade + promotion tier, and carries deterministic learnings.
 */

export interface AgentDimension {
  key: string
  label: string
  value: number
  weight: number
  data_available: boolean
}

export interface AgentLearning {
  text: string
  tone: string
}

export interface AgentScore {
  name: string
  display_name: string
  status: string
  grade: string | null
  score: number | null
  score_pct: number | null
  tier: string
  promoted: boolean
  event_count: number
  total_runs: number
  completed_runs: number
  failed_runs: number
  dimensions: AgentDimension[]
  learnings: AgentLearning[]
}

export interface AgentPerformanceResponse {
  agents: AgentScore[]
  promoted: number
  mode: string
  timestamp: string
}

export interface AgentActivity {
  trace_id: string | null
  status: string | null
  symbol: string | null
  created_at: string | null
}

export interface AgentHeartbeat {
  status: string | null
  event_count: number | null
  last_event: string | null
  last_seen: number | null
  seconds_ago: number | null
}

export interface AgentDetail extends AgentScore {
  heartbeat: AgentHeartbeat
  recent_activity: AgentActivity[]
  mode: string
  timestamp: string
}

/** Drill-in detail endpoint for one agent (path is dynamic, not in API_ENDPOINTS). */
export const agentDetailPath = (name: string): string =>
  `/dashboard/agents/${encodeURIComponent(name)}/detail`
