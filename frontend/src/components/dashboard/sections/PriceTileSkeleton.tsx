import { cn } from '@/lib/utils'
import { UI_RADIUS } from '@/lib/constants/ui'

/** Loading placeholder shaped like a real price tile so the layout doesn't shift on hydration. */
export function PriceTileSkeleton() {
  return (
    <div
      className={cn(
        UI_RADIUS.card,
        'border border-slate-200 p-3 dark:border-slate-800',
      )}
    >
      <div className="mb-1 h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-1 h-6 w-24 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-2 flex items-center justify-between">
        <div className="h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="h-3 w-12 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      </div>
    </div>
  )
}
