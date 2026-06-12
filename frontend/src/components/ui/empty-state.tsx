import type { ComponentType, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  message: string
  /** Optional secondary explanation line(s) under the message. */
  hint?: ReactNode
  icon?: ComponentType<{ className?: string }>
  className?: string
}

/** Canonical empty-state primitive — dashed surface + muted message (optional icon/hint). */
export function EmptyState({ message, hint, icon: Icon, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed bg-muted/30 px-4 py-10',
        className,
      )}
    >
      {Icon ? <Icon className="h-5 w-5 text-muted-foreground/50" aria-hidden /> : null}
      <p className="text-xs font-sans font-medium text-muted-foreground">{message}</p>
      {hint ? <div className="max-w-prose text-center text-xs text-muted-foreground/80">{hint}</div> : null}
    </div>
  )
}
