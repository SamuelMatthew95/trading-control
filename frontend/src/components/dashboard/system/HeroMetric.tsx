'use client'

import type { ComponentType } from 'react'

import { cn } from '@/lib/utils'

import { STATUS_COLOR } from './helpers'
import type { StatusTone } from './types'

export interface HeroMetricProps {
  label: string
  value: string
  status?: StatusTone
  icon?: ComponentType<{ className?: string }>
  sub?: string
}

export function HeroMetric({
  label,
  value,
  status = 'neutral',
  icon: Icon,
  sub,
}: HeroMetricProps) {
  const color = STATUS_COLOR[status]
  return (
    <div
      role="group"
      aria-label={label}
      className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          {label}
        </span>
        {Icon ? <Icon className={cn('h-4 w-4', color)} /> : null}
      </div>
      <span className={cn('text-2xl font-mono font-bold tabular-nums leading-tight', color)}>
        {value}
      </span>
      {sub ? (
        <span className="text-[11px] text-slate-500 dark:text-slate-400">{sub}</span>
      ) : null}
    </div>
  )
}
