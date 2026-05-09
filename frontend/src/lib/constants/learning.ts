/**
 * Learning-domain constants — fallback labels, proposal taxonomy, refresh
 * cadences, and threshold tunables that the UI used to inline as magic
 * numbers / lookup tables inside individual components.
 *
 * Single source of truth: change a label or threshold here and every
 * consumer updates. Never hard-code these values in a component.
 */

import type { Tone } from '@/lib/state/tone'

// ── Reasoning-agent fallback markers ──────────────────────────────────────
//
// The reasoning agent emits `fallback:<mode>` markers when the LLM is
// unavailable. The UI translates each mode into a human-readable label.

export const FALLBACK_LABELS: Record<string, string> = {
  skip_reasoning: 'Rule-based fallback decision',
  reject_signal: 'Rule-based fallback: signal rejected',
  use_last_reflection: 'Rule-based fallback: reused last reflection',
}

/** Default label for an unknown `fallback:<mode>` value. */
export const FALLBACK_UNKNOWN_LABEL = 'LLM unavailable'

/** Set of every translated fallback message — used to detect "fallback rows". */
export const FALLBACK_MESSAGES = new Set<string>([
  ...Object.values(FALLBACK_LABELS),
  FALLBACK_UNKNOWN_LABEL,
])

// ── Proposal taxonomy ─────────────────────────────────────────────────────
//
// The backend's proposal_type enum gets a friendly label and a Tone for
// the type chip. New types added on the backend should be reflected here.

export const PROPOSAL_TYPE_LABEL: Record<string, string> = {
  parameter_change: 'Param Change',
  code_change: 'Code Change',
  regime_adjustment: 'Regime Adjust',
  signal_weight_reduction: 'Weight Reduction',
  agent_suspension: 'Suspension',
  agent_retirement: 'Retirement',
  new_agent: 'New Agent',
}

export const PROPOSAL_TYPE_TONE: Record<string, Tone> = {
  parameter_change: 'info',
  code_change: 'info',
  regime_adjustment: 'warn',
  signal_weight_reduction: 'warn',
  agent_suspension: 'neg',
  agent_retirement: 'neg',
  new_agent: 'pos',
}

// ── Sharpe ratio thresholds ───────────────────────────────────────────────
//
// Sharpe is special-cased: not a [0,1] ratio. Above 1 is great, 0–1 is
// mediocre, < 0 is bad. Used in the Agent Performance metric tiles.

export const SHARPE_GREAT_THRESHOLD = 1
export const SHARPE_NEUTRAL_THRESHOLD = 0

// ── Pipeline freshness ────────────────────────────────────────────────────

/** A pipeline stage is considered "active" if its latest event is within this window. */
export const PIPELINE_FRESH_WINDOW_MS = 10 * 60 * 1000

// ── Stream stat freshness ─────────────────────────────────────────────────

/** A stream stat is "live" if its lastMessageTimestamp is within this window. */
export const STREAM_LIVE_WINDOW_MS = 60_000

// ── Recent-event stream → tone (System section recent events panel) ───────

export const RECENT_EVENT_TONE: Record<string, Tone> = {
  market_ticks: 'pos',
  signals: 'info',
  orders: 'warn',
}

// ── Pipeline stream names rendered on the System "Pipeline Status" panel ──

export const PIPELINE_STREAM_NAMES = [
  'market_ticks',
  'signals',
  'orders',
  'executions',
  'agent_logs',
  'risk_alerts',
  'notifications',
] as const

export type PipelineStreamName = (typeof PIPELINE_STREAM_NAMES)[number]
