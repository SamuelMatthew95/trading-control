/**
 * Presentational primitives for the System dashboard panels.
 */
import { cn } from '@/lib/utils'
import { sectionTitleClass } from '@/lib/dashboard-styles'
import type { StatusTone } from './types'
import type { DecisionAction } from './derive'

// Shared label recipe — alias of the canonical section title style.
export const LABEL_CLASS = sectionTitleClass
export const VALUE_CLASS = 'font-mono text-sm tabular-nums text-foreground'

export type HealthIndicator = {
  label: string
  tone: StatusTone
  value: string
}

export function statusToneClass(tone: StatusTone): string {
  switch (tone) {
    case 'ok':
      return 'bg-success ring-success/30'
    case 'warn':
      return 'bg-warning ring-warning/30'
    case 'err':
      return 'bg-danger ring-danger/30'
    default:
      return 'bg-muted-foreground ring-muted-foreground/30'
  }
}

export function actionClass(action: DecisionAction): string {
  switch (action) {
    case 'BUY':
      return 'text-success bg-success/10 ring-success/30'
    case 'SELL':
      return 'text-danger bg-danger/10 ring-danger/30'
    case 'SKIP':
      return 'text-warning bg-warning/10 ring-warning/30'
    default:
      return 'text-muted-foreground bg-muted-foreground/10 ring-muted-foreground/30'
  }
}

export function KpiStrip({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: StatusTone
}) {
  return (
    <div className="border-b px-3 py-2 last:border-b-0">
      <p className={LABEL_CLASS}>{label}</p>
      <p
        className={cn(
          VALUE_CLASS,
          tone === 'ok' && 'text-success',
          tone === 'warn' && 'text-warning',
          tone === 'err' && 'text-danger',
        )}
      >
        {value}
      </p>
    </div>
  )
}

export function StatePill({ label, tone, value }: HealthIndicator) {
  return (
    <div className="flex items-center justify-between gap-3 border-b px-3 py-2 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className={cn('h-2 w-2 rounded-full ring-4', statusToneClass(tone))} aria-hidden="true" />
        <span className="text-xs font-medium text-foreground/80">{label}</span>
      </div>
      <span className="font-mono text-2xs uppercase tracking-caps text-muted-foreground">{value}</span>
    </div>
  )
}
