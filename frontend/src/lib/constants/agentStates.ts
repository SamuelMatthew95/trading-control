/**
 * Agent heartbeat thresholds and key normalization.
 */

/** Agent is "Live" if its last heartbeat was within this window. */
export const AGENT_LIVE_THRESHOLD_MS = 10_000

/** Agent is "Stale" (not Idle) if its last heartbeat was within this window. */
export const AGENT_STALE_THRESHOLD_MS = 120_000

/**
 * Per-agent live-window overrides.
 *
 * Some agents (Reasoning) issue an LLM call between heartbeats that can take
 * 60-90s, so the default 10s threshold would flag them as Stale every cycle.
 */
export const AGENT_LIVE_THRESHOLD_OVERRIDES: Record<string, number> = {
  REASONING_AGENT: 90_000,
}

export function getLiveThresholdMs(agentKey: string): number {
  return AGENT_LIVE_THRESHOLD_OVERRIDES[agentKey] ?? AGENT_LIVE_THRESHOLD_MS
}

/** Normalize any name shape to canonical SCREAMING_SNAKE_CASE. */
export function canonicalAgentKey(name: string): string {
  return String(name ?? '').trim().toUpperCase().replace(/[\s-]+/g, '_')
}

/** Display-friendly version of an agent name (canonical → Title Case). */
export function displayAgentName(rawName: string): string {
  const canonical = canonicalAgentKey(rawName)
  if (canonical === 'IC_UPDATER') return 'Indicator Cache Updater'
  return String(rawName ?? '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (m) => m.toUpperCase())
}
