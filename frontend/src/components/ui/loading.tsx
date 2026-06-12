import { cn } from '@/lib/utils'
import { mutedClass } from '@/lib/dashboard-styles'
import { UI_COPY } from '@/constants/copy'

/** Canonical pulse placeholder block for loading layouts. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded bg-muted-foreground/10', className)} />
}

export interface LoadingStateProps {
  label?: string
  className?: string
}

/** Canonical inline loading message — shared wording, polite live region. */
export function LoadingState({ label = UI_COPY.loading.default, className }: LoadingStateProps) {
  return (
    <p role="status" aria-live="polite" className={cn(mutedClass, className)}>
      {label}
    </p>
  )
}
