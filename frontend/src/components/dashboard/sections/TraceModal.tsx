'use client'

import { useEffect, useState } from 'react'
import { ErrorState, LoadingState, SectionHeader } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForScore } from '@/lib/state'
import { getTrace } from '@/lib/api'
import { UI_TEXT } from '@/lib/constants/ui'
import type { TraceData } from '@/lib/types'

interface TraceModalProps {
  traceId: string
  onClose: () => void
}

export function TraceModal({ traceId, onClose }: TraceModalProps) {
  const [data, setData] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getTrace(traceId)
      .then((d) => {
        if (cancelled) return
        setData(d)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError('Failed to load trace')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [traceId])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-3xl overflow-y-auto rounded-[8px] border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <SectionHeader
          title="Trace"
          right={
            <>
              <span className="font-mono text-xs text-slate-700 dark:text-slate-300">
                {traceId.slice(0, 16)}…
              </span>
              <button
                onClick={onClose}
                className="text-xl font-bold leading-none text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                aria-label="Close trace modal"
              >
                ×
              </button>
            </>
          }
        />
        {loading ? <LoadingState /> : null}
        {error ? <ErrorState message={error} /> : null}
        {data ? (
          <div className="space-y-4">
            {data.agent_runs.length > 0 ? (
              <TraceSection title="Agent Runs">
                {data.agent_runs.map((r, i) => (
                  <div
                    key={`${traceId}-run-${i}`}
                    className="rounded-[4px] border border-slate-200 p-2 text-xs font-mono text-slate-700 dark:border-slate-700 dark:text-slate-300"
                  >
                    <span className="font-bold text-slate-900 dark:text-slate-100">
                      {String(r.agent_name ?? '—')}
                    </span>
                    {' · '}
                    {String(r.run_type ?? '')} · {String(r.status ?? '')}
                    {r.execution_time_ms != null ? (
                      <span className={UI_TEXT.muted}> · {String(r.execution_time_ms)}ms</span>
                    ) : null}
                  </div>
                ))}
              </TraceSection>
            ) : null}
            {data.agent_logs.length > 0 ? (
              <TraceSection title="Agent Logs">
                {data.agent_logs.map((lg, i) => (
                  <div
                    key={`${traceId}-log-${i}`}
                    className="rounded-[4px] border border-slate-200 p-2 text-xs font-mono text-slate-700 dark:border-slate-700 dark:text-slate-300"
                  >
                    <span className="text-slate-500">{String(lg.log_type ?? '—')}</span>
                    {' · '}
                    {String(lg.created_at ?? '')}
                  </div>
                ))}
              </TraceSection>
            ) : null}
            {data.agent_grades.length > 0 ? (
              <TraceSection title="Grades">
                {data.agent_grades.map((g, i) => {
                  const score = typeof g.score === 'number' && Number.isFinite(g.score) ? g.score : null
                  const tone = toneForScore(score)
                  return (
                    <div
                      key={`${traceId}-grade-${i}`}
                      className="flex items-center gap-2 rounded-[4px] border border-slate-200 p-2 text-xs font-mono text-slate-700 dark:border-slate-700 dark:text-slate-300"
                    >
                      <span>{String(g.grade_type ?? '—')}</span>
                      <span className={cn('font-bold', TONE_CLASSES[tone].text)}>
                        {score == null ? '—' : score.toFixed(1)}
                      </span>
                    </div>
                  )
                })}
              </TraceSection>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function TraceSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className={cn(UI_TEXT.label, 'mb-2')}>{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  )
}
