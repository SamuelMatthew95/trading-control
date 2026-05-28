'use client'

import type { ComponentType } from 'react'

import { cn } from '@/lib/utils'

import type { AlertVariant } from './types'

const ALERT_PALETTE: Record<AlertVariant, string> = {
  ok: 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300',
  warn: 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300',
  err: 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300',
  info: 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-900/40 dark:bg-blue-950/30 dark:text-blue-300',
}

export interface AlertBannerProps {
  variant: AlertVariant
  icon: ComponentType<{ className?: string }>
  message: string
  detail?: string
}

export function AlertBanner({ variant, icon: Icon, message, detail }: AlertBannerProps) {
  return (
    <div
      role="alert"
      className={cn('flex items-start gap-3 rounded-lg border px-3 py-2.5', ALERT_PALETTE[variant])}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="space-y-0.5">
        <p className="text-sm font-semibold">{message}</p>
        {detail ? <p className="text-xs opacity-90">{detail}</p> : null}
      </div>
    </div>
  )
}
