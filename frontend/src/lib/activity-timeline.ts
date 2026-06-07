/**
 * Pure logic for the Agents dashboard "Live Activity" timeline.
 *
 * The dashboard is otherwise a wall of *state* cards (confidence, status, PnL).
 * This turns the real event streams the store already holds into a single
 * chronological story of what the pipeline is *doing*: market data arriving,
 * each agent acting, decisions committed, and outcomes fired.
 *
 * No React here so the merge/normalize can be unit-tested in isolation; the
 * component only renders what this produces. Everything is grounded in real
 * store data — nothing is synthesized.
 */
import {
  AGENT_CHALLENGER,
  AGENT_EXECUTION,
  AGENT_GRADE,
  AGENT_IC_UPDATER,
  AGENT_PROPOSAL_APPLIER,
  AGENT_REFLECTION,
  AGENT_SIGNAL,
  AGENT_STRATEGY_PROPOSER,
  canonicalAgentKey,
} from '@/constants/agents'
import {
  STREAM_MARKET_EVENTS,
  STREAM_MARKET_TICKS,
  STREAM_ORDERS,
  STREAM_RISK_ALERTS,
  STREAM_EXECUTIONS,
} from '@/constants/streams'
import { parseTimestampMs } from '@/lib/formatters'
import type { AgentLog, Notification, RecentEvent } from '@/stores/useCodexStore'

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
  agentLogs?: AgentLog[]
}

const DEFAULT_LIMIT = 40
const MESSAGE_DETAIL_MAX = 60

// Raw market streams → human label. Only market data has no agent log / decision
// / notification of its own, so it is the one stream surfaced as a bare event;
// every other stage is sourced from the richer streams below.
const STREAM_STAGE: Record<string, { stage: ActivityStage; title: string }> = {
  [STREAM_MARKET_TICKS]: { stage: 'market', title: 'Market data updated' },
  [STREAM_MARKET_EVENTS]: { stage: 'market', title: 'Market event' },
}

// Canonical agent key → stage + verb for the per-agent activity lines.
// Reasoning and Notification agents are intentionally absent: their output is
// surfaced richer via the decisions and notifications sources, so logging them
// here too would just duplicate those.
const AGENT_STAGE: Record<string, { stage: ActivityStage; title: string }> = {
  [AGENT_SIGNAL]: { stage: 'signal', title: 'Signal generated' },
  [AGENT_EXECUTION]: { stage: 'execution', title: 'Execution' },
  [AGENT_GRADE]: { stage: 'grade', title: 'Trade graded' },
  [AGENT_IC_UPDATER]: { stage: 'learning', title: 'Factors reweighted' },
  [AGENT_REFLECTION]: { stage: 'learning', title: 'Reflection' },
  [AGENT_STRATEGY_PROPOSER]: { stage: 'proposal', title: 'Proposal drafted' },
  [AGENT_CHALLENGER]: { stage: 'agent', title: 'Challenger' },
  [AGENT_PROPOSAL_APPLIER]: { stage: 'proposal', title: 'Proposal applied' },
}

// Agent lifecycle transitions (instance spawn / retire) are written to
// agent_logs with log_type "lifecycle" and no real message — the backend's
// in-memory writer falls the message back to the literal "lifecycle". They are
// NOT pipeline output: an agent coming online is not a grade, a reflection, or
// a drafted proposal. Rendering them here falsely showed "Trade graded" /
// "Reflection" / "Proposal drafted" for agents that had merely started,
// directly contradicting the (correctly empty) Proposals and Learning pages
// when the learning loop is idle. The dedicated backend endpoints all filter by
// log_type (GRADE / REFLECTION / PROPOSAL), so the feed must do the same and
// surface only genuine output logs.
export function isLifecycleLog(log: AgentLog): boolean {
  return String(log.log_type ?? '').toLowerCase() === 'lifecycle'
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

function agentLogDetail(log: AgentLog): string | null {
  const action = typeof log.action === 'string' ? log.action.toLowerCase() : ''
  const symbol = typeof log.symbol === 'string' ? log.symbol : ''
  if (action && symbol) return `${action} ${symbol}`
  if (symbol) return symbol
  if (typeof log.message === 'string' && log.message) {
    return log.message.length > MESSAGE_DETAIL_MAX
      ? `${log.message.slice(0, MESSAGE_DETAIL_MAX - 1)}…`
      : log.message
  }
  return null
}

function agentLogTone(log: AgentLog): ActivityTone {
  const action = typeof log.action === 'string' ? log.action.toLowerCase() : ''
  if (action === 'buy') return 'buy'
  if (action === 'sell') return 'sell'
  return 'neutral'
}

// Market events carry the symbol + price the frame was about — surface them so a
// market row reads "BTC/USD · $60,781.58 · ▼ 12.30" instead of a bare, repeated
// "Market event" that tells the operator nothing about what actually happened.
function marketEventDetail(e: RecentEvent): string | null {
  const parts: string[] = []
  if (e.symbol) parts.push(e.symbol)
  if (typeof e.price === 'number' && Number.isFinite(e.price)) {
    parts.push(`$${e.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`)
  }
  if (typeof e.change === 'number' && Number.isFinite(e.change) && e.change !== 0) {
    parts.push(
      `${e.change > 0 ? '▲' : '▼'} ${Math.abs(e.change).toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
    )
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

/**
 * Merge market events, per-agent activity, decisions, and notifications into one
 * descending chronological feed. Pure + total — bad timestamps are skipped, ids
 * dedupe across re-renders, and the result is capped at `limit`.
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

  // 3) Per-agent activity — the signal / execution / grade / learning / proposal
  //    work each agent did, with real symbol/action detail.
  let logIndex = 0
  for (const log of input.agentLogs ?? []) {
    logIndex += 1
    // Agent spawn/retire churn is not pipeline output — skip it (see above).
    if (isLifecycleLog(log)) continue
    const key = canonicalAgentKey(String(log.agent_name || log.agent || ''))
    const mapped = AGENT_STAGE[key]
    if (!mapped) continue
    const ts = parseTimestampMs(log.timestamp || log.created_at)
    if (ts == null) continue
    items.push({
      id: `log-${String(log.id ?? `${key}-${logIndex}`)}-${ts}`,
      ts,
      stage: mapped.stage,
      title: mapped.title,
      detail: agentLogDetail(log),
      tone: agentLogTone(log),
      fallback: false,
    })
  }

  // 4) Market events — the one stage with no agent log of its own.
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
      detail: marketEventDetail(e),
      tone: 'neutral',
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
