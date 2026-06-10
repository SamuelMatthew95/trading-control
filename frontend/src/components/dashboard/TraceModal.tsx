'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/apiClient'
import { cn } from '@/lib/utils'
import { sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'

type TraceData = {
  trace_id: string
  agent_runs: Array<Record<string, unknown>>
  agent_logs: Array<Record<string, unknown>>
  agent_grades: Array<Record<string, unknown>>
}

export function TraceModal({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [data, setData] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(api(`/dashboard/trace/${encodeURIComponent(traceId)}`))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => { setData(d as TraceData); setLoading(false) })
      .catch(() => { setError('Failed to load trace'); setLoading(false) })
  }, [traceId])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <p className={cn(sectionTitleClass)}>
            Trace:{' '}
            <span className="font-mono text-slate-700 dark:text-slate-300">
              {traceId.slice(0, 16)}…
            </span>
          </p>
          <button
            onClick={onClose}
            className="text-xl font-bold leading-none text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          >
            ×
          </button>
        </div>

        {loading && <p className={mutedClass}>Loading…</p>}
        {error && <p className="text-sm text-danger">{error}</p>}

        {data &&
          data.agent_runs.length === 0 &&
          data.agent_logs.length === 0 &&
          data.agent_grades.length === 0 && (
            <p className={mutedClass}>
              No details found for this trace. In memory mode (no database) trace
              history is cleared on restart — only live, in-session traces are
              available here.
            </p>
          )}

        {data && (
          <div className="space-y-4">
            {data.agent_runs.length > 0 && (
              <div>
                <p className={cn(sectionTitleClass, 'mb-2')}>Agent Runs</p>
                <div className="space-y-1">
                  {data.agent_runs.map((r, i) => (
                    <div
                      key={`${traceId}-run-${i}`}
                      className="rounded border border-slate-200 p-2 font-mono text-xs text-slate-700 dark:border-slate-700 dark:text-slate-300"
                    >
                      <span className="font-bold text-slate-900 dark:text-slate-100">
                        {String(r.agent_name ?? '--')}
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
                <p className={cn(sectionTitleClass, 'mb-2')}>Agent Logs</p>
                <div className="space-y-1">
                  {data.agent_logs.map((lg, i) => (
                    <div
                      key={`${traceId}-log-${i}`}
                      className="rounded border border-slate-200 p-2 font-mono text-xs text-slate-700 dark:border-slate-700 dark:text-slate-300"
                    >
                      <span className="text-slate-500">{String(lg.log_type ?? '--')}</span>
                      {' · '}
                      {String(lg.created_at ?? '')}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.agent_grades.length > 0 && (
              <div>
                <p className={cn(sectionTitleClass, 'mb-2')}>Grades</p>
                <div className="space-y-1">
                  {data.agent_grades.map((g, i) => {
                    const score =
                      typeof g.score === 'number' && Number.isFinite(g.score) ? g.score : null
                    const scoreColor =
                      score == null
                        ? 'text-slate-500 dark:text-slate-400'
                        : score >= 70
                          ? 'text-success'
                          : score >= 40
                            ? 'text-warning'
                            : 'text-danger'
                    return (
                      <div
                        key={`${traceId}-grade-${i}`}
                        className="flex items-center gap-2 rounded border border-slate-200 p-2 font-mono text-xs text-slate-700 dark:border-slate-700 dark:text-slate-300"
                      >
                        <span>{String(g.grade_type ?? '--')}</span>
                        <span className={cn('font-bold', scoreColor)}>
                          {score == null ? '--' : score.toFixed(1)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
