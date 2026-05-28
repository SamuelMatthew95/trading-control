'use client'

import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'

import { formatTimestamp } from './helpers'
import type { PersistedHistoryItem, PersistedStreamCount } from './types'

const MAX_ROWS = 10

const emptyLabel = (isInMemoryMode: boolean): string =>
  isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'

interface PanelProps {
  title: string
  children: React.ReactNode
}

function Panel({ title, children }: PanelProps) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <p className={cn(mutedClass, 'mb-2')}>{title}</p>
      {children}
    </div>
  )
}

export interface PersistedHistoryProps {
  isInMemoryMode: boolean
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]
  onSelectTrace: (traceId: string) => void
}

export function PersistedHistory(props: PersistedHistoryProps) {
  const {
    isInMemoryMode,
    persistedCounts,
    persistedEvents,
    persistedLogs,
    onSelectTrace,
  } = props
  const emptyText = emptyLabel(isInMemoryMode)

  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Persisted Event History</p>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Panel title="Processed counts by stream">
          {persistedCounts.length === 0 ? (
            <p className={mutedClass}>{emptyText}</p>
          ) : (
            <div className="space-y-1">
              {persistedCounts.slice(0, MAX_ROWS).map((row) => (
                <div key={row.stream} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-slate-600 dark:text-slate-300">{row.stream}</span>
                  <span className="tabular-nums text-slate-900 dark:text-slate-100">
                    {row.processed_count.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Latest persisted events">
          {persistedEvents.length === 0 ? (
            <p className={mutedClass}>{emptyText}</p>
          ) : (
            <div className="space-y-1">
              {persistedEvents.slice(0, MAX_ROWS).map((evt) => (
                <div key={evt.id} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-slate-600 dark:text-slate-300">{evt.kind ?? '--'}</span>
                  <span className="text-slate-500">{formatTimestamp(evt.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Latest persisted agent logs">
          {persistedLogs.length === 0 ? (
            <p className={mutedClass}>{emptyText}</p>
          ) : (
            <div className="space-y-1">
              {persistedLogs.slice(0, MAX_ROWS).map((log) => (
                <button
                  key={log.id}
                  type="button"
                  disabled={!log.trace_id}
                  className="flex w-full items-center justify-between rounded px-1 py-1 text-left text-xs font-mono hover:bg-slate-100 disabled:cursor-default disabled:hover:bg-transparent dark:hover:bg-slate-800"
                  onClick={() => log.trace_id && onSelectTrace(log.trace_id)}
                >
                  <span className="text-slate-600 dark:text-slate-300">{log.kind ?? '--'}</span>
                  <span className="text-slate-500">{formatTimestamp(log.created_at)}</span>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
