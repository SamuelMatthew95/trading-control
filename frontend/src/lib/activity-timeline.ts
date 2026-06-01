/**
 * Pure logic for the Agents dashboard "Live Activity" timeline.
 *
 * The dashboard is otherwise a wall of *state* cards (confidence, status, PnL).
 * This turns the real event streams the store already holds into a single
 * chronological story of what the pipeline is *doing* — decisions it committed
 * to, outcomes it fired, and the raw stage events flowing between agents.
 *
 * No React here so the merge/normalize can be unit-tested in isolation; the
 * component only renders what this produces. Everything is grounded in real
 * store data — nothing is synthesized.
 */
import {
  STREAM_AGENT_GRADES,
  STREAM_AGENT_LOGS,
  STREAM_DECISIONS,
  STREAM_EXECUTIONS,
  STREAM_MARKET_EVENTS,
  STREAM_MARKET_TICKS,
  STREAM_NOTIFICATIONS,
  STREAM_ORDERS,
  STREAM_RISK_ALERTS,
  STREAM_SIGNALS,
} from '@/constants/streams'
import { parseTimestampMs } from '@/lib/formatters'
import type { Notification, RecentEvent } from '@/stores/useCodexStore'

/** Pipeline stage an activity item belongs to — drives its colour + icon. */
export type ActivityStage =
  | 'market'
  | 'signal'
  | 'decision'
  | 'execution'
  | 'grade'
  | 'proposal'
  | 'risk'
  | 'learning'
  | 'notification'
  | 'agent'
  | 'system'

export type ActivityTone = 'buy' | 'sell' | 'good' | 'warn' | 'bad' | 'neutral'

export interface ActivityItem {
  id: string
  /** Epoch ms — sort key and time-label source. */
  ts: number
  stage: ActivityStage
  title: string
  detail: string | null
  tone: ActivityTone
  /** True when produced by a rule-based fallback (LLM unavailable). */
  fallback: boolean
}

export interface ActivityTimelineInput {
  recentEvents?: RecentEvent[]
  recentDecisions?: Array<Record<string, unknown>>
  notifications?: Notification[]
}

const DEFAULT_LIMIT = 40

// Raw stream → human stage + verb. Decisions and notifications are intentionally
// absent: they have richer dedicated sources below, so surfacing the bare stream
// event too would just duplicate them.
const STREAM_STAGE: Record<string, { stage: ActivityStage; title: string }> = {
  [STREAM_MARKET_TICKS]: { stage: 'market', title: 'Market data updated' },
  [STREAM_MARKET_EVENTS]: { stage: 'market', title: 'Market event' },
  [STREAM_SIGNALS]: { stage: 'signal', title: 'Signal generated' },
  [STREAM_ORDERS]: { stage: 'execution', title: 'Order placed' },
  [STREAM_EXECUTIONS]: { stage: 'execution', title: 'Order executed' },
  [STREAM_AGENT_GRADES]: { stage: 'grade', title: 'Trade graded' },
  [STREAM_RISK_ALERTS]: { stage: 'risk', title: 'Risk alert' },
  [STREAM_AGENT_LOGS]: { stage: 'agent', title: 'Agent activity' },
}

// A decision is a rule-based fallback (not model reasoning) when the agent
// could not run the LLM: it sets llm_succeeded=false and/or prefixes its
// reasoning summary with "fallback:". Mirrors RecentDecisionsPanel.
function isFallbackDecision(d: Record<string, unknown>): boolean {
  if (d.llm_succeeded === false) return true
  const summary = typeof d.reasoning_summary === 'string' ? d.reasoning_summary : ''
  return summary.startsWith('fallback:')
}

function decisionTone(action: string): ActivityTone {
  if (action === 'buy') return 'buy'
  if (action === 'sell') return 'sell'
  return 'neutral'
}

function notificationStage(n: Notification): ActivityStage {
  const type = (n.notification_type ?? '').toLowerCase()
  const source = (n.stream_source ?? '').toLowerCase()
  if (type.startsWith('trade.') || source === STREAM_EXECUTIONS || source === STREAM_ORDERS) {
    return 'execution'
  }
  if (type.includes('risk') || source === STREAM_RISK_ALERTS) return 'risk'
  if (type.includes('proposal')) return 'proposal'
  if (type.includes('grade') || type.includes('performance')) return 'grade'
  if (type.includes('learn') || type.includes('reflection')) return 'learning'
  return 'notification'
}

function notificationTone(n: Notification): ActivityTone {
  const action = (n.action ?? '').toLowerCase()
  if (action === 'buy') return 'buy'
  if (action === 'sell') return 'sell'
  const severity = (n.severity ?? '').toUpperCase()
  if (severity === 'ERROR' || severity === 'CRITICAL') return 'bad'
  if (severity === 'WARNING' || severity === 'WARN') return 'warn'
  if (typeof n.pnl === 'number' && n.pnl > 0) return 'good'
  if (typeof n.pnl === 'number' && n.pnl < 0) return 'bad'
  return 'neutral'
}

function notificationDetail(n: Notification): string | null {
  const parts: string[] = []
  if (n.symbol) parts.push(n.symbol)
  if (typeof n.fill_price === 'number' && Number.isFinite(n.fill_price)) {
    parts.push(`$${n.fill_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`)
  }
  if (typeof n.pnl === 'number' && Number.isFinite(n.pnl)) {
    parts.push(`${n.pnl >= 0 ? '+' : ''}$${n.pnl.toFixed(2)}`)
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

/**
 * Merge decisions, notifications, and raw stream events into one descending
 * chronological feed. Pure + total — bad timestamps are skipped, ids dedupe
 * across re-renders, and the result is capped at `limit`.
 */
export function buildActivityTimeline(
  input: ActivityTimelineInput,
  limit: number = DEFAULT_LIMIT,
): ActivityItem[] {
  const items: ActivityItem[] = []

  // 1) Decisions — the BUY / SELL / HOLD the system actually committed to.
  for (const d of input.recentDecisions ?? []) {
    const ts = parseTimestampMs(d.timestamp)
    if (ts == null) continue
    const action = String(d.action ?? '').toLowerCase()
    const symbol = typeof d.symbol === 'string' && d.symbol ? d.symbol : '—'
    const conf = Number(d.confidence)
    const confTxt = Number.isFinite(conf) ? ` · ${(conf * 100).toFixed(0)}%` : ''
    items.push({
      id: `decision-${String(d.id ?? d.trace_id ?? ts)}`,
      ts,
      stage: 'decision',
      title: action ? `${action.toUpperCase()} decided` : 'Decision made',
      detail: `${symbol}${confTxt}`,
      tone: decisionTone(action),
      fallback: isFallbackDecision(d),
    })
  }

  // 2) Notifications — human-facing outcomes (fills, risk, proposals).
  for (const n of input.notifications ?? []) {
    const ts = parseTimestampMs(n.timestamp)
    if (ts == null) continue
    items.push({
      id: `notif-${n.id}`,
      ts,
      stage: notificationStage(n),
      title: n.title || n.message || 'Notification',
      detail: notificationDetail(n),
      tone: notificationTone(n),
      fallback: false,
    })
  }

  // 3) Raw stage events — the pipeline firing between agents, for stages the
  //    richer sources above do not already cover.
  for (const e of input.recentEvents ?? []) {
    const mapped = STREAM_STAGE[e.stream]
    if (!mapped) continue
    const ts = parseTimestampMs(e.timestamp)
    if (ts == null) continue
    items.push({
      id: `event-${e.stream}-${e.msgId}`,
      ts,
      stage: mapped.stage,
      title: mapped.title,
      detail: null,
      tone: mapped.stage === 'risk' ? 'warn' : 'neutral',
      fallback: false,
    })
  }

  items.sort((a, b) => b.ts - a.ts)

  const seen = new Set<string>()
  const deduped: ActivityItem[] = []
  for (const item of items) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    deduped.push(item)
  }
  return deduped.slice(0, Math.max(0, limit))
}

// Streams that map to a richer source and are intentionally not rendered as raw
// events. Exported so the channel set has one home (used by the timeline only).
export const TIMELINE_RICHER_STREAMS = [STREAM_DECISIONS, STREAM_NOTIFICATIONS] as const
