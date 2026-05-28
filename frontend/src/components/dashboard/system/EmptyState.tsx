'use client'

import type { ComponentType } from 'react'

export interface EmptyStateProps {
  message: string
  icon?: ComponentType<{ className?: string }>
}

export function EmptyState({ message, icon: Icon }: EmptyStateProps) {
  return (
    <div className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-10 dark:border-slate-800 dark:bg-slate-900/30">
      {Icon ? <Icon className="h-5 w-5 text-slate-300 dark:text-slate-600" /> : null}
      <p className="text-xs font-sans font-medium text-slate-400 dark:text-slate-600">
        {message}
      </p>
    </div>
  )
}
