import type { ReactNode } from 'react'

// Freshness of each agent data source (ages in ms), surfaced in diagnostics.
export interface WiringFreshness {
  heartbeatAgeMs: number | null
  instanceAgeMs: number | null
  logAgeMs: number | null
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-10 dark:border-slate-800 dark:bg-slate-900/30">
      <p className="text-xs font-sans font-medium text-slate-400 dark:text-slate-600">{message}</p>
    </div>
  )
}

// Subtle section divider so the page reads as grouped zones, not one long stack.
export function GroupLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="px-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500">
      {children}
    </h2>
  )
}
