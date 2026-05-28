'use client'

import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'

import { PRICE_FRESHNESS_MS, SYSTEM_STREAMS } from './helpers'
import type { StreamStat } from './types'

export interface StreamActivityProps {
  streamStats: Record<string, StreamStat>
  /** Used so tests can pin time deterministically. Defaults to Date.now in production. */
  now?: () => number
}

const isLiveStream = (stat: StreamStat, nowMs: number): boolean =>
  Boolean(
    stat.lastMessageTimestamp &&
      nowMs - new Date(stat.lastMessageTimestamp).getTime() < PRICE_FRESHNESS_MS,
  )

const streamDotClass = (stat: StreamStat, nowMs: number): string => {
  if (isLiveStream(stat, nowMs)) return 'animate-pulse bg-emerald-500'
  return stat.count > 0 ? 'bg-amber-400' : 'bg-slate-400'
}

export function StreamActivity({ streamStats, now = Date.now }: StreamActivityProps) {
  const nowMs = now()
  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Stream Activity</p>
      <div className="space-y-1.5">
        {SYSTEM_STREAMS.map((streamName) => {
          const stat = streamStats[streamName] ?? {
            count: 0,
            lastMessageTimestamp: null,
          }
          return (
            <div
              key={streamName}
              className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
            >
              <div className="flex items-center gap-2">
                <span className={cn('h-2 w-2 rounded-full', streamDotClass(stat, nowMs))} />
                <span className="text-xs font-mono text-slate-700 dark:text-slate-300">
                  {streamName}
                </span>
              </div>
              <span className="text-sm font-mono font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                {stat.count.toLocaleString()}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
