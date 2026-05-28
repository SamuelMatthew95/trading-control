'use client'

import { Activity } from 'lucide-react'

import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { streamEventBadgeClass } from '@/lib/dashboard-helpers'
import { cn } from '@/lib/utils'

import { EmptyState } from './EmptyState'
import { formatRelativeTime, formatTimestamp } from './helpers'
import type { RecentEventLike } from './types'

const MAX_EVENTS = 15

const eventKey = (event: RecentEventLike, fallbackIndex: number): string => {
  const stream = event.stream ?? 'evt'
  const timestamp = event.timestamp ?? ''
  const msgId = event.msgId && event.msgId !== 'n/a' ? event.msgId : String(fallbackIndex)
  return `${stream}-${timestamp}-${msgId}`
}

const countByStream = (events: RecentEventLike[]): Array<[string, number]> => {
  const counts = new Map<string, number>()
  for (const event of events) {
    const stream = event.stream ?? '—'
    counts.set(stream, (counts.get(stream) ?? 0) + 1)
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
}

export interface RecentEventsProps {
  events: RecentEventLike[]
  wsConnected: boolean
  /** Override Date.now for deterministic tests. */
  now?: () => number
}

export function RecentEvents({ events, wsConnected, now = Date.now }: RecentEventsProps) {
  const visibleEvents = events.slice(0, MAX_EVENTS)
  const streamSummary = countByStream(visibleEvents)

  return (
    <div className={cardClass}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className={sectionTitleClass}>Recent Events</p>
        {streamSummary.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {streamSummary.map(([stream, count]) => (
              <span
                key={stream}
                className={cn(
                  'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold',
                  streamEventBadgeClass(stream === '—' ? null : stream),
                )}
              >
                <span>{stream}</span>
                <span className="font-mono tabular-nums opacity-80">{count}</span>
              </span>
            ))}
          </div>
        ) : null}
      </div>
      {visibleEvents.length === 0 ? (
        <EmptyState
          message={wsConnected ? 'No websocket events yet' : 'Stream disconnected'}
          icon={Activity}
        />
      ) : (
        <div className="space-y-1">
          {visibleEvents.map((event, index) => (
            <div
              key={eventKey(event, index)}
              className="flex items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-1.5 dark:border-slate-800"
            >
              <span
                className={cn(
                  'inline-block min-w-[110px] rounded px-2 py-0.5 text-center text-xs font-semibold',
                  streamEventBadgeClass(event.stream),
                )}
              >
                {event.stream ?? '—'}
              </span>
              <div className="flex flex-1 items-center justify-end gap-3 text-xs">
                <span className="font-mono font-semibold tabular-nums text-slate-700 dark:text-slate-200">
                  {formatRelativeTime(event.timestamp, now)}
                </span>
                <span className="font-mono tabular-nums text-slate-400 dark:text-slate-500">
                  {formatTimestamp(event.timestamp)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
