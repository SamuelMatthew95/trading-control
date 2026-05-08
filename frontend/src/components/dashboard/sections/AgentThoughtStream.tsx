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

function formatAgentMessage(raw: unknown): string {
  if (raw == null || raw === '') return 'N/A'
  const text = String(raw)
  if (text.startsWith('fallback:')) {
    const mode = text.slice('fallback:'.length)
    return FALLBACK_LABELS[mode] ?? 'LLM unavailable'
  }
  return text
}

function buildAgentLabel(log: AgentLog): string {
  return String(log?.agent_name ?? log?.agent ?? '') || 'N/A'
}

function buildConfidenceText(confidence: number | null): string {
  if (confidence == null) return '—'
  return (confidence * 100).toFixed(0)
}

function readTraceId(log: AgentLog): string | null {
  return typeof log?.trace_id === 'string' && log.trace_id ? log.trace_id : null
}

function buildLogKey(log: AgentLog, agentLabel: string, index: number): string {
  if (log?.id != null) return String(log.id)
  return `${agentLabel}-${log?.timestamp ?? ''}-${index}`
}

function readLogMessage(log: AgentLog): unknown {
  return log?.message ?? log?.summary ?? log?.primary_edge
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
  const agentLabel = buildAgentLabel(log)
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
      <p className={cn(UI_TEXT.body, 'leading-relaxed')}>{formatAgentMessage(readLogMessage(log))}</p>
    </div>
  )
}

function visibleLogs(logs: AgentLog[]): AgentLog[] {
  return logs.slice(-AGENT_LOG_MAX_ROWS).slice().reverse()
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
                key={buildLogKey(log, buildAgentLabel(log), index)}
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
