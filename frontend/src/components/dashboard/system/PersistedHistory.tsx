'use client'

import { Database, FileSearch } from 'lucide-react'

import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'

import { formatRelativeTime, formatTimestamp } from './helpers'
import type { PersistedHistoryItem, PersistedStreamCount } from './types'

const MAX_ROWS = 10

interface PanelProps {
  title: string
  children: React.ReactNode
}

function Panel({ title, children }: PanelProps) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <p
        className={cn(
          'mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400',
        )}
      >
        {title}
      </p>
      {children}
    </div>
  )
}

function MemoryModeNotice() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-3 dark:border-amber-900/40 dark:bg-amber-950/20">
      <Database className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="space-y-1">
        <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">
          Running in memory mode — no DB persistence
        </p>
        <p className="text-xs text-amber-700/80 dark:text-amber-300/70">
          Events and agent logs live in-process only and will be lost on restart. Connect
          PostgreSQL to enable durable history, trace replay, and learning aggregates.
        </p>
      </div>
    </div>
  )
}

function PersistenceDisabledNotice() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50/40 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/30">
      <FileSearch className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" />
      <div className="space-y-1">
        <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">
          Persistence not enabled
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          No persisted events or logs were returned by the API. Check that the event
          recorder is running and that the history endpoint is reachable.
        </p>
      </div>
    </div>
  )
}

interface EmptySectionProps {
  message: string
}

function EmptySection({ message }: EmptySectionProps) {
  return <p className={cn(mutedClass, 'italic')}>{message}</p>
}

export interface PersistedHistoryProps {
  isInMemoryMode: boolean
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]
  onSelectTrace: (traceId: string) => void
  /** Override Date.now for deterministic tests. */
  now?: () => number
}

export function PersistedHistory(props: PersistedHistoryProps) {
  const {
    isInMemoryMode,
    persistedCounts,
    persistedEvents,
    persistedLogs,
    onSelectTrace,
    now = Date.now,
  } = props

  const hasAnyData =
    persistedCounts.length > 0 || persistedEvents.length > 0 || persistedLogs.length > 0

  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Persisted Event History</p>

      {isInMemoryMode && !hasAnyData ? (
        <MemoryModeNotice />
      ) : !hasAnyData ? (
        <PersistenceDisabledNotice />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <Panel title="Processed counts">
            {persistedCounts.length === 0 ? (
              <EmptySection message="No stream counts yet" />
            ) : (
              <div className="space-y-1">
                {persistedCounts.slice(0, MAX_ROWS).map((row) => (
                  <div
                    key={row.stream}
                    className="flex items-center justify-between text-xs font-mono"
                  >
                    <span className="text-slate-600 dark:text-slate-300">{row.stream}</span>
                    <span className="tabular-nums text-slate-900 dark:text-slate-100">
                      {row.processed_count.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Latest events">
            {persistedEvents.length === 0 ? (
              <EmptySection message="No events yet" />
            ) : (
              <div className="space-y-1">
                {persistedEvents.slice(0, MAX_ROWS).map((evt) => (
                  <div
                    key={evt.id}
                    className="flex items-center justify-between gap-2 text-xs font-mono"
                  >
                    <span className="truncate text-slate-700 dark:text-slate-200">
                      {evt.kind ?? '—'}
                    </span>
                    <span className="shrink-0 text-slate-400" title={formatTimestamp(evt.created_at)}>
                      {formatRelativeTime(evt.created_at, now)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Latest agent logs">
            {persistedLogs.length === 0 ? (
              <EmptySection message="No logs yet" />
            ) : (
              <div className="space-y-1">
                {persistedLogs.slice(0, MAX_ROWS).map((log) => (
                  <button
                    key={log.id}
                    type="button"
                    disabled={!log.trace_id}
                    title={
                      log.trace_id ? 'Open trace' : 'No trace_id — cannot drill in'
                    }
                    className="flex w-full items-center justify-between gap-2 rounded px-1 py-1 text-left text-xs font-mono transition-colors hover:bg-slate-100 disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent dark:hover:bg-slate-800"
                    onClick={() => log.trace_id && onSelectTrace(log.trace_id)}
                  >
                    <span className="truncate text-slate-700 dark:text-slate-200">
                      {log.kind ?? '—'}
                    </span>
                    <span
                      className="shrink-0 text-slate-400"
                      title={formatTimestamp(log.created_at)}
                    >
                      {formatRelativeTime(log.created_at, now)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Panel>
        </div>
      )}
    </div>
  )
}
