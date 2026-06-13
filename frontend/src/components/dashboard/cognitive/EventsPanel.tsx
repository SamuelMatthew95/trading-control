'use client'

import { cn } from '@/lib/utils'
import { NO_DATA } from '@/constants/copy'
import type { CognitiveEvent } from '@/types/cognitive'

import { card, COPY } from './cognitive-ui'

export function EventsPanel({ events }: { events: CognitiveEvent[] }) {
  const recent = [...events].reverse()
  return (
    <div className={cn(card, 'max-h-[28rem] overflow-auto')}>
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 z-sticky bg-card text-muted-foreground dark:bg-popover">
          <tr>
            <th className="py-1 pr-2">{COPY.eventColumns.seq}</th>
            <th className="py-1 pr-2">{COPY.eventColumns.type}</th>
            <th className="py-1 pr-2">{COPY.eventColumns.source}</th>
            <th className="py-1">{COPY.eventColumns.trace}</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((event) => (
            <tr key={event.seq} className="border-t">
              <td className="py-1 pr-2 font-mono text-muted-foreground">{event.seq}</td>
              <td className="py-1 pr-2 font-medium text-foreground/80">{event.type}</td>
              <td className="py-1 pr-2 text-muted-foreground">{event.source || NO_DATA}</td>
              <td className="py-1 font-mono text-muted-foreground">{event.trace_id || NO_DATA}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
