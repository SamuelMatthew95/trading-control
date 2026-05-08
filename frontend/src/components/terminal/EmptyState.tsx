import type { ComponentType } from 'react'
import { cn } from '@/lib/utils'
import { UI_RADIUS } from '@/lib/constants/ui'

interface EmptyStateProps {
  message: string
  icon?: ComponentType<{ className?: string }>
  className?: string
}

/**
 * "No data yet" placeholder — dashed border, muted text. Use this any time
 * a panel has *no* rows to render and is *not* in an error state.
 */
export function EmptyState({ message, icon: Icon, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex min-h-28 flex-col items-center justify-center gap-2 border border-dashed border-slate-300 px-4 py-8 dark:border-slate-700',
        UI_RADIUS.card,
        className,
      )}
    >
      {Icon ? <Icon className="h-5 w-5 text-slate-400" /> : null}
      <p className="text-sm text-slate-400">{message}</p>
    </div>
  )
}
