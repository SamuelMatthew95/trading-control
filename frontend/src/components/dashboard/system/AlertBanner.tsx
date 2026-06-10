'use client'

import type { ComponentType } from 'react'

import { cn } from '@/lib/utils'

import type { AlertVariant } from './types'

const ALERT_PALETTE: Record<AlertVariant, string> = {
  ok: 'border-success/30 bg-success/10 text-success',
  warn: 'border-warning/30 bg-warning/10 text-warning',
  err: 'border-danger/30 bg-danger/10 text-danger',
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
