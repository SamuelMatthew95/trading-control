'use client'

import {
  TerminalCard,
  SectionHeader,
  EmptyState,
  TerminalTable,
  TerminalRow,
  TerminalCell,
} from '@/components/terminal'
import { GradeChip } from '@/components/trading'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForRatio } from '@/lib/state'
import { formatTimestamp } from '@/lib/format'
import type { GradeRecord } from '@/lib/api'

const HEADERS = ['Grade', 'Score', 'LLM Health', 'Rate Lim', 'Delay', 'Time'] as const

interface GradeHistoryPanelProps {
  grades: GradeRecord[]
}

export function GradeHistoryPanel({ grades }: GradeHistoryPanelProps) {
  if (grades.length === 0) {
    return <EmptyState message="No graded learning records yet" />
  }
  return (
    <TerminalCard padded>
      <SectionHeader title="Grade History" />
      <TerminalTable headers={HEADERS}>
        {grades.map((g, i) => {
          const m = g.metrics ?? {}
          const llmHealth = m.llm_health_score
          const rateLim = m.llm_rate_limited
          const delayMs = m.llm_effective_delay_ms
          const llmTone = toneForRatio(llmHealth)
          return (
            <TerminalRow key={i}>
              <TerminalCell numeric>
                <GradeChip grade={g.grade} />
              </TerminalCell>
              <TerminalCell numeric>
                {g.score_pct != null ? `${g.score_pct}%` : '—'}
              </TerminalCell>
              <TerminalCell numeric>
                {llmHealth != null ? (
                  <span className={TONE_CLASSES[llmTone].text}>
                    {(llmHealth * 100).toFixed(0)}%
                  </span>
                ) : (
                  '—'
                )}
              </TerminalCell>
              <TerminalCell numeric>
                {rateLim != null ? (
                  <span
                    className={cn(
                      rateLim > 0 ? TONE_CLASSES.warn.text : 'text-slate-500 dark:text-slate-400',
                    )}
                  >
                    {rateLim}
                  </span>
                ) : (
                  '—'
                )}
              </TerminalCell>
              <TerminalCell numeric>{delayMs != null ? `${delayMs}ms` : '—'}</TerminalCell>
              <TerminalCell numeric>{formatTimestamp(g.timestamp)}</TerminalCell>
            </TerminalRow>
          )
        })}
      </TerminalTable>
    </TerminalCard>
  )
}
