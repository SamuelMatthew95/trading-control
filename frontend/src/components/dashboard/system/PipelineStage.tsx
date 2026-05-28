'use client'

import { ChevronRight } from 'lucide-react'

import { cn } from '@/lib/utils'

import type { StageStatus } from './types'

const STAGE_DOT_COLOR: Record<StageStatus, string> = {
  live: 'bg-emerald-500',
  flowing: 'bg-emerald-500',
  idle: 'bg-amber-400',
  stalled: 'bg-rose-500',
}

const STAGE_LABEL: Record<StageStatus, string> = {
  live: 'LIVE',
  flowing: 'FLOWING',
  idle: 'IDLE',
  stalled: 'STALLED',
}

export interface PipelineStageProps {
  label: string
  count: number
  status: StageStatus
  isLast?: boolean
}

export function PipelineStage({ label, count, status, isLast }: PipelineStageProps) {
  const dotColor = STAGE_DOT_COLOR[status]
  const dotAnim = status === 'live' || status === 'flowing' ? 'animate-pulse' : ''
  const stageLabel = STAGE_LABEL[status]
  return (
    <div className="flex items-center gap-2">
      <div className="flex min-w-[130px] flex-col items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-1.5">
          <span className={cn('h-2 w-2 rounded-full', dotColor, dotAnim)} />
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
            {label}
          </span>
        </div>
        <span className="text-xl font-mono font-bold tabular-nums text-slate-900 dark:text-slate-100">
          {count.toLocaleString()}
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          {stageLabel}
        </span>
      </div>
      {!isLast ? (
        <ChevronRight
          aria-hidden="true"
          className="h-5 w-5 shrink-0 text-slate-300 dark:text-slate-700"
        />
      ) : null}
    </div>
  )
}
