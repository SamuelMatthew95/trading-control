/**
 * Agent / runtime status vocabulary.
 *
 * The product surfaces several status spaces:
 *  - Heartbeat-derived AGENT status:        Live | Stale | Error | Idle
 *  - Pipeline-stage status (learning loop): Active | Idle | Error
 *  - Trade lifecycle:                       OPEN | FILLED | REJECTED | CANCELLED | PENDING | CLOSED
 *  - Buy/sell side:                         buy | sell  (also long | short for positions)
 *
 * Every status maps to exactly one Tone via `toneFor*` so the UI cannot drift.
 */

import type { Tone } from './tone'

// ── Agent heartbeat status ──────────────────────────────────────────────────

export type AgentStatus = 'Live' | 'Stale' | 'Error' | 'Idle'

const AGENT_STATUS_PRIORITY: Record<AgentStatus, number> = {
  Live: 0,
  Stale: 1,
  Error: 2,
  Idle: 3,
}

const AGENT_STATUS_TONE: Record<AgentStatus, Tone> = {
  Live: 'pos',
  Stale: 'warn',
  Error: 'neg',
  Idle: 'muted',
}

export function toneForAgentStatus(status: AgentStatus): Tone {
  return AGENT_STATUS_TONE[status]
}

/** Pick the more important status (Live wins over Stale wins over Error...). */
export function pickHigherPriorityStatus(
  current: AgentStatus | undefined,
  incoming: AgentStatus,
): AgentStatus {
  if (!current) return incoming
  return AGENT_STATUS_PRIORITY[incoming] < AGENT_STATUS_PRIORITY[current]
    ? incoming
    : current
}

export function compareAgentStatus(a: AgentStatus, b: AgentStatus): number {
  return AGENT_STATUS_PRIORITY[a] - AGENT_STATUS_PRIORITY[b]
}

// ── Pipeline stage status ───────────────────────────────────────────────────

export type PipelineStageStatus = 'Active' | 'Idle' | 'Error'

const PIPELINE_STAGE_TONE: Record<PipelineStageStatus, Tone> = {
  Active: 'pos',
  Idle: 'muted',
  Error: 'neg',
}

export function toneForPipelineStage(status: PipelineStageStatus): Tone {
  return PIPELINE_STAGE_TONE[status]
}

// ── System status ───────────────────────────────────────────────────────────

export type SystemStatus = 'trading' | 'booting' | 'error' | 'idle'

const SYSTEM_STATUS_TONE: Record<SystemStatus, Tone> = {
  trading: 'pos',
  booting: 'warn',
  error: 'neg',
  idle: 'muted',
}

export function toneForSystemStatus(status: string): Tone {
  return SYSTEM_STATUS_TONE[(status as SystemStatus) ?? 'idle'] ?? 'muted'
}

// ── Trade side ──────────────────────────────────────────────────────────────

export type TradeSide = 'buy' | 'sell' | 'long' | 'short'

export function toneForTradeSide(side: string | null | undefined): Tone {
  const s = String(side ?? '').toLowerCase()
  if (s === 'buy' || s === 'long') return 'pos'
  if (s === 'sell' || s === 'short') return 'neg'
  return 'muted'
}

// ── Order status ────────────────────────────────────────────────────────────

export type OrderStatus = 'OPEN' | 'FILLED' | 'REJECTED' | 'CANCELLED' | 'PENDING' | 'CLOSED'

export function toneForOrderStatus(status: string | null | undefined): Tone {
  const s = String(status ?? '').toUpperCase()
  if (s === 'FILLED' || s === 'CLOSED' || s === 'EXECUTED' || s === 'COMPLETED') return 'pos'
  if (s === 'REJECTED' || s === 'CANCELLED' || s === 'FAILED') return 'neg'
  if (s === 'PENDING') return 'warn'
  return 'info'
}

/** Heuristic: is this order/trade considered closed for accounting purposes? */
export function isClosedTrade(order: Record<string, unknown> | null | undefined): boolean {
  if (!order) return false
  const status = String(order.status ?? '').toLowerCase()
  if (status === 'filled' || status === 'closed' || status === 'executed' || status === 'completed') return true
  if (order.filled_at != null) return true
  return false
}

// ── Letter grades ──────────────────────────────────────────────────────────

export type Grade = 'A' | 'B' | 'C' | 'D' | 'F'

const GRADE_TONE: Record<Grade, Tone> = {
  A: 'pos',
  B: 'pos',
  C: 'warn',
  D: 'neg',
  F: 'neg',
}

export function toneForGrade(grade: string | null | undefined): Tone {
  if (!grade) return 'muted'
  const g = grade.toUpperCase() as Grade
  return GRADE_TONE[g] ?? 'muted'
}

/** 0–100 score → tone (≥70 pos, ≥40 warn, else neg). */
export function toneForScore(score: number | null | undefined): Tone {
  if (score == null || !Number.isFinite(score)) return 'muted'
  if (score >= 70) return 'pos'
  if (score >= 40) return 'warn'
  return 'neg'
}

/** 0–1 ratio → tone (≥0.8 pos, ≥0.5 warn, else neg). */
export function toneForRatio(ratio: number | null | undefined): Tone {
  if (ratio == null || !Number.isFinite(ratio)) return 'muted'
  if (ratio >= 0.8) return 'pos'
  if (ratio >= 0.5) return 'warn'
  return 'neg'
}
