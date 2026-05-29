/**
 * Canonical agent identity for the frontend.
 *
 * Mirrors the SCREAMING_SNAKE_CASE names in `api/constants.py` (ALL_AGENT_NAMES).
 * These strings are the contract used for Redis heartbeat keys, agent-log
 * `agent_name` fields, and `/dashboard/state` `agent_statuses`. Never hardcode
 * the raw string anywhere in the UI — import the constant so a rename is a
 * single-line change that the type checker can follow.
 */

export const AGENT_SIGNAL = 'SIGNAL_AGENT'
export const AGENT_REASONING = 'REASONING_AGENT'
export const AGENT_EXECUTION = 'EXECUTION_ENGINE'
export const AGENT_GRADE = 'GRADE_AGENT'
export const AGENT_IC_UPDATER = 'IC_UPDATER'
export const AGENT_REFLECTION = 'REFLECTION_AGENT'
export const AGENT_STRATEGY_PROPOSER = 'STRATEGY_PROPOSER'
export const AGENT_NOTIFICATION = 'NOTIFICATION_AGENT'

export const ALL_AGENT_NAMES = [
  AGENT_SIGNAL,
  AGENT_REASONING,
  AGENT_EXECUTION,
  AGENT_GRADE,
  AGENT_IC_UPDATER,
  AGENT_REFLECTION,
  AGENT_STRATEGY_PROPOSER,
  AGENT_NOTIFICATION,
] as const

export type AgentName = (typeof ALL_AGENT_NAMES)[number]

/**
 * Normalize any agent label ("Signal Agent", "signal-agent", "SIGNAL_AGENT")
 * to its canonical SCREAMING_SNAKE_CASE key so heartbeats, logs, and lifecycle
 * rows from different sources reconcile to one identity.
 */
export function canonicalAgentKey(name: string): string {
  return name.trim().toUpperCase().replace(/[\s-]+/g, '_')
}

/**
 * Human-readable label for an agent name. Title-cases the SCREAMING_SNAKE_CASE
 * key, with a friendlier expansion for the IC updater.
 */
export function agentDisplayName(rawName: string): string {
  if (canonicalAgentKey(rawName) === AGENT_IC_UPDATER) return 'Indicator Cache Updater'
  return rawName
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (m) => m.toUpperCase())
}
