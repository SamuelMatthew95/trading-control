import { cn } from '@/lib/utils'
import { UI_RADIUS } from '@/lib/constants/ui'

interface LoadingStateProps {
  /** Optional message; when omitted just shows the skeleton bar. */
  message?: string
  className?: string
}

/**
 * Generic loading placeholder for panels. Use Skeleton primitives when you
 * want to mimic the final layout (e.g. PriceTileSkeleton).
 */
export function LoadingState({ message, className }: LoadingStateProps) {
  return (
    <div
      className={cn(
        'flex min-h-28 items-center justify-center gap-3 border border-dashed border-slate-200 px-4 py-8 dark:border-slate-800',
        UI_RADIUS.card,
        className,
      )}
    >
      <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400" aria-hidden />
      <p className="text-sm text-slate-400">{message ?? 'Loading…'}</p>
    </div>
  )
}
