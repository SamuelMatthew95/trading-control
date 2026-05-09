'use client'

import { TerminalCard, SectionHeader, EmptyState, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForRatio } from '@/lib/state'
import { extractConfidence, formatTimeAgo, parseTimestamp } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { AGENT_LOG_MAX_ROWS } from '@/lib/constants/trading'
import {
  FALLBACK_LABELS,
  FALLBACK_MESSAGES,
  FALLBACK_UNKNOWN_LABEL,
} from '@/lib/constants/learning'
import {
  ROW_DIVIDER_SKIP_FIRST,
  ROW_WRAP,
  SCORE_CHIP,
  SCROLL_FADE_BOTTOM,
  SCROLL_LIST_AGENT_LOG,
  ROW_TITLE_BOLD,
  STACK_TIGHT,
  TRACE_BUTTON,
} from '@/lib/styles'
import type { AgentLog } from '@/stores/useCodexStore'

interface AgentThoughtStreamProps {
  logs: AgentLog[]
  onTraceClick: (traceId: string) => void
}

// ── Pure helpers ──────────────────────────────────────────────────────────

/**
 * Translate `fallback:<mode>` markers anywhere in the message. The reasoning
 * agent emits both bare ("fallback:skip_reasoning") and embedded
 * ("HOLD (30%) — fallback:skip_reasoning") forms. Mode → label mapping
 * lives in lib/constants/learning so it stays in sync with the backend
 * fallback enum.
 */
function formatAgentMessage(raw: unknown): string {
  if (raw == null || raw === '') return ''
  const text = String(raw).trim()
  if (!text) return ''
  return text.replace(/fallback:(\w+)/g, (_match, mode: string) => {
    return FALLBACK_LABELS[mode] ?? FALLBACK_UNKNOWN_LABEL
  })
}

function readAgentName(log: AgentLog): string {
  return String(log?.agent_name ?? log?.agent ?? '').trim()
}

function readTraceId(log: AgentLog): string | null {
  return typeof log?.trace_id === 'string' && log.trace_id ? log.trace_id : null
}

function readLogMessage(log: AgentLog): string {
  return formatAgentMessage(log?.message ?? log?.summary ?? log?.primary_edge)
}

function readTimestamp(log: AgentLog): Date | null {
  return parseTimestamp(log?.timestamp ?? log?.created_at)
}

function isFallbackMessage(message: string): boolean {
  return FALLBACK_MESSAGES.has(message)
}

// ── Aggregation ───────────────────────────────────────────────────────────

interface ThoughtRow {
  agent: string
  message: string
  /** Latest confidence value seen for this (agent, message) group. */
  confidence: number | null
  /** Latest trace_id for this group — used for the trace button. */
  traceId: string | null
  /** Latest timestamp seen — used for the time-ago label. */
  lastSeen: Date | null
  /** How many duplicate logs collapsed into this row. */
  count: number
}

interface ThoughtStreamView {
  rows: ThoughtRow[]
  fallbackCount: number
}

/**
 * Collapse incoming agent logs into distinct (agent, message) thoughts.
 *
 * The reasoning agent often emits identical "Rule-based fallback decision"
 * lines for every signal when the LLM is unavailable. Showing five copies
 * of the same string is noise — collapse to one row with a `×N` badge so
 * the operator can see *that* fallbacks are happening *and how many* in
 * one glance.
 *
 * Returns the deduped rows plus a separate fallbackCount so the UI can
 * surface a single banner instead of repeating the same fallback message.
 */
function buildThoughtView(logs: AgentLog[]): ThoughtStreamView {
  const recent = logs.slice(-AGENT_LOG_MAX_ROWS * 4).slice().reverse()
  const groups = new Map<string, ThoughtRow>()
  let fallbackCount = 0

  for (const log of recent) {
    const agent = readAgentName(log)
    if (!agent) continue
    const message = readLogMessage(log)
    if (!message) continue
    if (isFallbackMessage(message)) {
      fallbackCount += 1
      continue
    }

    const key = `${agent}|${message}`
    const existing = groups.get(key)
    const confidence = extractConfidence(log as Record<string, unknown>)
    const traceId = readTraceId(log)
    const ts = readTimestamp(log)

    if (!existing) {
      groups.set(key, {
        agent,
        message,
        confidence,
        traceId,
        lastSeen: ts,
        count: 1,
      })
      continue
    }
    existing.count += 1
    // Keep the most recent confidence/trace/timestamp seen for this thought.
    if (ts && (!existing.lastSeen || ts > existing.lastSeen)) {
      existing.lastSeen = ts
      existing.confidence = confidence ?? existing.confidence
      existing.traceId = traceId ?? existing.traceId
    }
  }

  const rows = Array.from(groups.values())
    .sort((a, b) => {
      const aTs = a.lastSeen?.getTime() ?? 0
      const bTs = b.lastSeen?.getTime() ?? 0
      return bTs - aTs
    })
    .slice(0, AGENT_LOG_MAX_ROWS)

  return { rows, fallbackCount }
}

function buildConfidenceText(confidence: number | null): string {
  if (confidence == null) return '—'
  return `${(confidence * 100).toFixed(0)}%`
}

// ── Sub-components ────────────────────────────────────────────────────────

function TraceLinkButton(props: { traceId: string; onTraceClick: (id: string) => void }) {
  const { traceId, onTraceClick } = props
  const handleClick = () => onTraceClick(traceId)
  return (
    <button onClick={handleClick} className={TRACE_BUTTON}>
      trace:{traceId.slice(0, 8)}…
    </button>
  )
}

const LOG_ROW_HEADER = cn('mb-1', ROW_WRAP)
const REPEAT_BADGE = cn(SCORE_CHIP, 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300')

interface ThoughtRowViewProps {
  row: ThoughtRow
  onTraceClick: (traceId: string) => void
}

function ThoughtRowView(props: ThoughtRowViewProps) {
  const { row, onTraceClick } = props
  const tone = toneForRatio(row.confidence)
  return (
    <div className={cn(ROW_DIVIDER_SKIP_FIRST, 'py-2')}>
      <div className={LOG_ROW_HEADER}>
        <p className={ROW_TITLE_BOLD}>{row.agent}</p>
        <span className={cn(SCORE_CHIP, TONE_CLASSES[tone].soft)}>
          {buildConfidenceText(row.confidence)}
        </span>
        {row.count > 1 ? <span className={REPEAT_BADGE}>×{row.count}</span> : null}
        {row.lastSeen ? (
          <span className={UI_TEXT.muted}>{formatTimeAgo(row.lastSeen)}</span>
        ) : null}
        {row.traceId ? (
          <TraceLinkButton traceId={row.traceId} onTraceClick={onTraceClick} />
        ) : null}
      </div>
      <p className={cn(UI_TEXT.body, 'leading-relaxed')}>{row.message}</p>
    </div>
  )
}

interface FallbackBannerProps {
  count: number
}

function FallbackBanner(props: FallbackBannerProps) {
  if (props.count === 0) return null
  const label =
    props.count === 1
      ? '1 rule-based decision (LLM unavailable)'
      : `${props.count} rule-based decisions (LLM unavailable)`
  return (
    <div
      className={cn(
        ROW_DIVIDER_SKIP_FIRST,
        'flex items-center gap-2 py-2 text-sm',
        TONE_CLASSES.warn.text,
      )}
    >
      <span className={cn('h-2 w-2 rounded-full', TONE_CLASSES.warn.bg)} aria-hidden />
      {label}
    </div>
  )
}

// ── Top-level ─────────────────────────────────────────────────────────────

export function AgentThoughtStream(props: AgentThoughtStreamProps) {
  const { logs, onTraceClick } = props
  const view = buildThoughtView(logs)
  const isEmpty = view.rows.length === 0 && view.fallbackCount === 0

  return (
    <TerminalCard>
      <SectionHeader
        title="Agent Thought Stream"
        right={<StateIndicator tone="pos" label="Live" pulse />}
      />
      {isEmpty ? (
        <EmptyState message="No active agents" />
      ) : (
        <div className={SCROLL_LIST_AGENT_LOG}>
          <div className={STACK_TIGHT}>
            <FallbackBanner count={view.fallbackCount} />
            {view.rows.map((row) => (
              <ThoughtRowView
                key={`${row.agent}|${row.message}`}
                row={row}
                onTraceClick={onTraceClick}
              />
            ))}
          </div>
          <div className={SCROLL_FADE_BOTTOM} />
        </div>
      )}
    </TerminalCard>
  )
}
