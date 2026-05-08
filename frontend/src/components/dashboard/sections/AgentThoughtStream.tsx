'use client'

import { TerminalCard, SectionHeader, EmptyState, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForRatio } from '@/lib/state'
import { toFiniteNumber } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { AGENT_LOG_MAX_ROWS } from '@/lib/constants/trading'
import type { AgentLog } from '@/stores/useCodexStore'

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

interface AgentThoughtStreamProps {
  logs: AgentLog[]
  onTraceClick: (traceId: string) => void
}

export function AgentThoughtStream({ logs, onTraceClick }: AgentThoughtStreamProps) {
  return (
    <TerminalCard>
      <SectionHeader
        title="Agent Thought Stream"
        right={<StateIndicator tone="pos" label="Live" pulse />}
      />
      {logs.length === 0 ? (
        <EmptyState message="No active agents" />
      ) : (
        <div className="relative max-h-80 overflow-y-auto">
          <div className="space-y-2">
            {logs
              .slice(-AGENT_LOG_MAX_ROWS)
              .reverse()
              .map((log, index) => {
                const confidence = toFiniteNumber(log?.confidence)
                const confidencePct = confidence == null ? '—' : (confidence * 100).toFixed(0)
                const tone = toneForRatio(confidence)
                const agentLabel = String(log?.agent_name ?? log?.agent ?? '') || 'N/A'
                const traceId = typeof log?.trace_id === 'string' ? log.trace_id : null
                return (
                  <div
                    key={String(log?.id ?? `${agentLabel}-${log?.timestamp ?? ''}-${index}`)}
                    className="border-t border-slate-200 py-2 first:border-t-0 dark:border-slate-800"
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <p className="text-sm font-bold text-slate-900 dark:text-slate-100">
                        {agentLabel}
                      </p>
                      <span
                        className={cn(
                          'rounded-[4px] px-2 py-0.5 text-xs font-semibold',
                          TONE_CLASSES[tone].soft,
                        )}
                      >
                        {confidencePct}%
                      </span>
                      {traceId ? (
                        <button
                          onClick={() => onTraceClick(traceId)}
                          className="rounded-[4px] px-1.5 py-0.5 text-[10px] font-mono text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
                        >
                          trace:{traceId.slice(0, 8)}…
                        </button>
                      ) : null}
                    </div>
                    <p className={cn(UI_TEXT.body, 'leading-relaxed')}>
                      {formatAgentMessage(log?.message ?? log?.summary ?? log?.primary_edge)}
                    </p>
                  </div>
                )
              })}
          </div>
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-white to-transparent dark:from-slate-900" />
        </div>
      )}
    </TerminalCard>
  )
}
