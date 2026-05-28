'use client'

import { Activity } from 'lucide-react'

import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { streamEventBadgeClass } from '@/lib/dashboard-helpers'
import { cn } from '@/lib/utils'

import { EmptyState } from './EmptyState'
import { formatTimestamp } from './helpers'
import type { RecentEventLike } from './types'

const MAX_EVENTS = 15
const MSG_ID_DISPLAY_LENGTH = 16

const eventKey = (event: RecentEventLike, fallbackIndex: number): string => {
  const stream = event.stream ?? 'evt'
  const timestamp = event.timestamp ?? ''
  const msgId = event.msgId && event.msgId !== 'n/a' ? event.msgId : String(fallbackIndex)
  return `${stream}-${timestamp}-${msgId}`
}

export interface RecentEventsProps {
  events: RecentEventLike[]
  wsConnected: boolean
}

export function RecentEvents({ events, wsConnected }: RecentEventsProps) {
  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Recent Events</p>
      {events.length === 0 ? (
        <EmptyState
          message={wsConnected ? 'No websocket events yet' : 'Stream disconnected'}
          icon={Activity}
        />
      ) : (
        <div className="space-y-1.5">
          {events.slice(0, MAX_EVENTS).map((event, index) => (
            <div
              key={eventKey(event, index)}
              className="grid grid-cols-[120px_1fr_110px] items-center gap-3 rounded-lg border border-slate-200 px-3 py-1.5 dark:border-slate-800"
            >
              <span
                className={cn(
                  'inline-block rounded px-2 py-0.5 text-xs font-semibold',
                  streamEventBadgeClass(event.stream),
                )}
              >
                {event.stream ?? '—'}
              </span>
              <span className="text-xs font-mono text-slate-500">
                {event.msgId && event.msgId !== 'n/a'
                  ? event.msgId.slice(0, MSG_ID_DISPLAY_LENGTH)
                  : '—'}
              </span>
              <span className="text-right text-xs font-mono text-slate-500">
                {formatTimestamp(event.timestamp)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
