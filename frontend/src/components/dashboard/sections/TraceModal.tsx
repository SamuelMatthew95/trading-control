'use client'

import { useEffect, useState } from 'react'
import { ErrorState, LoadingState, SectionHeader } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForScore } from '@/lib/state'
import { getTrace } from '@/lib/api'
import { UI_TEXT } from '@/lib/constants/ui'
import { MODAL_OVERLAY, MODAL_PANEL, STACK } from '@/lib/styles'
import type { TraceData } from '@/lib/types'

interface TraceModalProps {
  traceId: string
  onClose: () => void
}

interface TraceFetchState {
  data: TraceData | null
  loading: boolean
  error: string | null
}

const INITIAL_STATE: TraceFetchState = {
  data: null,
  loading: true,
  error: null,
}

function useTraceFetch(traceId: string): TraceFetchState {
  const [state, setState] = useState<TraceFetchState>(INITIAL_STATE)

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, error: null })
    getTrace(traceId).then(
      (data) => {
        if (cancelled) return
        setState({ data, loading: false, error: null })
      },
      () => {
        if (cancelled) return
        setState({ data: null, loading: false, error: 'Failed to load trace' })
      },
    )
    return () => {
      cancelled = true
    }
  }, [traceId])

  return state
}

function TraceSection(props: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className={cn(UI_TEXT.label, 'mb-2')}>{props.title}</p>
      <div className="space-y-1">{props.children}</div>
    </div>
  )
}

interface RunRowProps {
  traceId: string
  index: number
  run: Record<string, unknown>
}

function RunRow(props: RunRowProps) {
  const { traceId, index, run } = props
  const executionTimeMs =
    typeof run.execution_time_ms === 'number' ? run.execution_time_ms : null
  return (
    <div
      key={`${traceId}-run-${index}`}
      className="rounded-[4px] border border-slate-200 p-2 text-xs font-mono text-slate-700 dark:border-slate-700 dark:text-slate-300"
    >
      <span className="font-bold text-slate-900 dark:text-slate-100">
        {String(run.agent_name ?? '—')}
      </span>
      {' · '}
      {String(run.run_type ?? '')} · {String(run.status ?? '')}
      {executionTimeMs != null ? (
        <span className={UI_TEXT.muted}> · {executionTimeMs}ms</span>
      ) : null}
    </div>
  )
}

function LogRow(props: { traceId: string; index: number; log: Record<string, unknown> }) {
  const { traceId, index, log } = props
  return (
    <div
      key={`${traceId}-log-${index}`}
      className="rounded-[4px] border border-slate-200 p-2 text-xs font-mono text-slate-700 dark:border-slate-700 dark:text-slate-300"
    >
      <span className="text-slate-500">{String(log.log_type ?? '—')}</span>
      {' · '}
      {String(log.created_at ?? '')}
    </div>
  )
}

function GradeRow(props: { traceId: string; index: number; grade: Record<string, unknown> }) {
  const { traceId, index, grade } = props
  const score = typeof grade.score === 'number' && Number.isFinite(grade.score) ? grade.score : null
  const tone = toneForScore(score)
  return (
    <div
      key={`${traceId}-grade-${index}`}
      className="flex items-center gap-2 rounded-[4px] border border-slate-200 p-2 text-xs font-mono text-slate-700 dark:border-slate-700 dark:text-slate-300"
    >
      <span>{String(grade.grade_type ?? '—')}</span>
      <span className={cn('font-bold', TONE_CLASSES[tone].text)}>
        {score == null ? '—' : score.toFixed(1)}
      </span>
    </div>
  )
}

function TraceBody(props: { data: TraceData }) {
  const { data } = props
  return (
    <div className={STACK}>
      {data.agent_runs.length > 0 ? (
        <TraceSection title="Agent Runs">
          {data.agent_runs.map((run, i) => (
            <RunRow key={`run-${i}`} traceId={data.trace_id} index={i} run={run} />
          ))}
        </TraceSection>
      ) : null}
      {data.agent_logs.length > 0 ? (
        <TraceSection title="Agent Logs">
          {data.agent_logs.map((log, i) => (
            <LogRow key={`log-${i}`} traceId={data.trace_id} index={i} log={log} />
          ))}
        </TraceSection>
      ) : null}
      {data.agent_grades.length > 0 ? (
        <TraceSection title="Grades">
          {data.agent_grades.map((g, i) => (
            <GradeRow key={`grade-${i}`} traceId={data.trace_id} index={i} grade={g} />
          ))}
        </TraceSection>
      ) : null}
    </div>
  )
}

function TraceCloseButton(props: { onClose: () => void }) {
  return (
    <button
      onClick={props.onClose}
      className="text-xl font-bold leading-none text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
      aria-label="Close trace modal"
    >
      ×
    </button>
  )
}

function stopPropagation(event: React.MouseEvent<HTMLDivElement>): void {
  event.stopPropagation()
}

export function TraceModal(props: TraceModalProps) {
  const { traceId, onClose } = props
  const { data, loading, error } = useTraceFetch(traceId)

  return (
    <div className={MODAL_OVERLAY} onClick={onClose}>
      <div className={MODAL_PANEL} onClick={stopPropagation}>
        <SectionHeader
          title="Trace"
          right={
            <>
              <span className="font-mono text-xs text-slate-700 dark:text-slate-300">
                {traceId.slice(0, 16)}…
              </span>
              <TraceCloseButton onClose={onClose} />
            </>
          }
        />
        {loading ? <LoadingState /> : null}
        {error ? <ErrorState message={error} /> : null}
        {data ? <TraceBody data={data} /> : null}
      </div>
    </div>
  )
}
