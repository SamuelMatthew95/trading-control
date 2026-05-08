'use client'

import { TerminalCard, SectionHeader, EmptyState, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForRatio } from '@/lib/state'
import { toFiniteNumber } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { AGENT_LOG_MAX_ROWS } from '@/lib/constants/trading'
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

const FALLBACK_LABELS: Record<string, string> = {
  skip_reasoning: 'Rule-based fallback decision',
  reject_signal: 'Rule-based fallback: signal rejected',
  use_last_reflection: 'Rule-based fallback: reused last reflection',
}

/**
 * Translate `fallback:<mode>` markers WHEREVER they appear in the message.
 * The reasoning agent emits both bare markers ("fallback:skip_reasoning")
 * and embedded forms ("HOLD (30%) — fallback:skip_reasoning"). The previous
 * implementation only handled the prefix form, so embedded markers leaked
 * raw to the UI.
 */
function formatAgentMessage(raw: unknown): string {
  if (raw == null || raw === '') return ''
  const text = String(raw).trim()
  if (!text) return ''
  return text.replace(/fallback:(\w+)/g, (_match, mode: string) => {
    return FALLBACK_LABELS[mode] ?? 'LLM unavailable'
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

function buildConfidenceText(confidence: number | null): string {
  if (confidence == null) return '—'
  return (confidence * 100).toFixed(0)
}

function buildLogKey(log: AgentLog, agentLabel: string, index: number): string {
  if (log?.id != null) return String(log.id)
  return `${agentLabel}-${log?.timestamp ?? ''}-${index}`
}

/**
 * Drop logs that carry no real signal:
 *   - missing/blank agent_name (renders as "N/A")
 *   - empty message after fallback translation
 * And dedupe per (trace_id, message) so the reasoning agent's parallel
 * "decision" + "summary" writes for the same trace don't both render.
 * Keeps the FIRST occurrence (newest, since we reverse before this runs).
 */
function visibleLogs(logs: AgentLog[]): AgentLog[] {
  const recent = logs.slice(-AGENT_LOG_MAX_ROWS * 2).slice().reverse()
  const seen = new Set<string>()
  const out: AgentLog[] = []
  for (const log of recent) {
    const agentName = readAgentName(log)
    if (!agentName) continue
    const message = readLogMessage(log)
    if (!message) continue
    const traceId = readTraceId(log) ?? ''
    const dedupeKey = `${traceId}|${message}`
    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)
    out.push(log)
    if (out.length >= AGENT_LOG_MAX_ROWS) break
  }
  return out
}

function TraceLinkButton(props: { traceId: string; onTraceClick: (id: string) => void }) {
  const { traceId, onTraceClick } = props
  const handleClick = () => onTraceClick(traceId)
  return (
    <button onClick={handleClick} className={TRACE_BUTTON}>
      trace:{traceId.slice(0, 8)}…
    </button>
  )
}

interface AgentLogRowProps {
  log: AgentLog
  index: number
  onTraceClick: (traceId: string) => void
}

const LOG_ROW_HEADER = cn('mb-1', ROW_WRAP)

function AgentLogRow(props: AgentLogRowProps) {
  const { log, index, onTraceClick } = props
  const confidence = toFiniteNumber(log?.confidence)
  const tone = toneForRatio(confidence)
  const agentLabel = readAgentName(log)
  const traceId = readTraceId(log)
  return (
    <div key={buildLogKey(log, agentLabel, index)} className={cn(ROW_DIVIDER_SKIP_FIRST, 'py-2')}>
      <div className={LOG_ROW_HEADER}>
        <p className={ROW_TITLE_BOLD}>{agentLabel}</p>
        <span className={cn(SCORE_CHIP, TONE_CLASSES[tone].soft)}>
          {buildConfidenceText(confidence)}%
        </span>
        {traceId ? <TraceLinkButton traceId={traceId} onTraceClick={onTraceClick} /> : null}
      </div>
      <p className={cn(UI_TEXT.body, 'leading-relaxed')}>{readLogMessage(log)}</p>
    </div>
  )
}

export function AgentThoughtStream(props: AgentThoughtStreamProps) {
  const { logs, onTraceClick } = props
  const rows = visibleLogs(logs)
  return (
    <TerminalCard>
      <SectionHeader
        title="Agent Thought Stream"
        right={<StateIndicator tone="pos" label="Live" pulse />}
      />
      {rows.length === 0 ? (
        <EmptyState message="No active agents" />
      ) : (
        <div className={SCROLL_LIST_AGENT_LOG}>
          <div className={STACK_TIGHT}>
            {rows.map((log, index) => (
              <AgentLogRow
                key={buildLogKey(log, readAgentName(log), index)}
                log={log}
                index={index}
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
