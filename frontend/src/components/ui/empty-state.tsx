import { type ComponentType } from 'react'

interface EmptyStateProps {
  message: string
  icon?: ComponentType<{ className?: string }>
}

export function EmptyState({ message, icon: Icon }: EmptyStateProps) {
  return (
    <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed border-slate-300 px-4 py-10 dark:border-slate-700">
      <div className="flex items-center gap-2">
        {Icon ? <Icon className="h-4 w-4 text-slate-500 dark:text-slate-400" /> : null}
        <p className="text-sm font-sans text-slate-500 dark:text-slate-400">{message}</p>
      </div>
    </div>
  )
}
