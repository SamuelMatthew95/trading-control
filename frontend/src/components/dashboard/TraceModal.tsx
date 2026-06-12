'use client'

import { useEffect, useState } from 'react'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { api } from '@/lib/apiClient'
import { cn } from '@/lib/utils'
import { sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { scoreColorClass } from '@/lib/dashboard-helpers'
import { Modal } from '@/components/ui/modal'
import { LoadingState } from '@/components/ui/loading'

type TraceData = {
  trace_id: string
  agent_runs: Array<Record<string, unknown>>
  agent_logs: Array<Record<string, unknown>>
  agent_grades: Array<Record<string, unknown>>
}

const traceRowClass = 'rounded border p-2 font-mono text-xs text-foreground/80'

export function TraceModal({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [data, setData] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(api(`/dashboard/trace/${encodeURIComponent(traceId)}`))
        if (cancelled) return
        // 404 is an expected outcome, not a failure: system notifications and
        // fallback decisions carry a trace_id but never write pipeline rows.
        if (r.status === 404) {
          setNotFound(true)
          return
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = (await r.json()) as TraceData
        if (!cancelled) setData(d)
      } catch {
        if (!cancelled) setError(UI_COPY.trace.loadError)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [traceId])

  const isEmptyTrace =
    notFound ||
    (data != null &&
      data.agent_runs.length === 0 &&
      data.agent_logs.length === 0 &&
      data.agent_grades.length === 0)

  return (
    <Modal
      onClose={onClose}
      size="lg"
      title={`${UI_COPY.trace.title} ${traceId.slice(0, 16)}…`}
    >
      {loading && <LoadingState label={UI_COPY.trace.loading} />}
      {error && <p className="text-sm text-danger">{error}</p>}

      {isEmptyTrace && <p className={mutedClass}>{UI_COPY.trace.emptyTrace}</p>}

      {data && (
        <div className="space-y-4">
          {data.agent_runs.length > 0 && (
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.trace.agentRuns}</p>
              <div className="space-y-1">
                {data.agent_runs.map((r, i) => (
                  <div key={`${traceId}-run-${i}`} className={traceRowClass}>
                    <span className="font-bold text-foreground">
                      {String(r.agent_name ?? NO_DATA)}
                    </span>
                    {' · '}
                    {String(r.run_type ?? '')} · {String(r.status ?? '')}
                    {r.execution_time_ms != null && (
                      <span className={mutedClass}> · {String(r.execution_time_ms)}ms</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.agent_logs.length > 0 && (
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.trace.agentLogs}</p>
              <div className="space-y-1">
                {data.agent_logs.map((lg, i) => (
                  <div key={`${traceId}-log-${i}`} className={traceRowClass}>
                    <span className="text-muted-foreground">{String(lg.log_type ?? NO_DATA)}</span>
                    {' · '}
                    {String(lg.created_at ?? '')}
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.agent_grades.length > 0 && (
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.trace.grades}</p>
              <div className="space-y-1">
                {data.agent_grades.map((g, i) => {
                  const score =
                    typeof g.score === 'number' && Number.isFinite(g.score) ? g.score : null
                  return (
                    <div
                      key={`${traceId}-grade-${i}`}
                      className={cn(traceRowClass, 'flex items-center gap-2')}
                    >
                      <span>{String(g.grade_type ?? NO_DATA)}</span>
                      <span className={cn('font-bold', scoreColorClass(score))}>
                        {score == null ? NO_DATA : score.toFixed(1)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
