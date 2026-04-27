'use client'

import { cn } from '@/lib/utils'

export type SystemStatusState = 'active' | 'idle' | 'error'

export function SystemStatus({ state }: { state: SystemStatusState }) {
  const label = state === 'active' ? 'Active' : state === 'error' ? 'Error' : 'Idle'
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-2 py-1">
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          state === 'active' ? 'bg-emerald-500 animate-pulse' : state === 'error' ? 'bg-rose-500 animate-pulse' : 'bg-slate-500'
        )}
      />
      <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-slate-300">{label}</span>
    </div>
  )
}
