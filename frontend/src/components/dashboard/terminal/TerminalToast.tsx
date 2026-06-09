'use client'

import { cn } from '@/lib/utils'
import type { ToastKind, ToastMessage } from './types'

const TONE_BY_KIND: Record<ToastKind, string> = {
  buy: 'border-[var(--up)] text-[var(--up)]',
  sell: 'border-[var(--down)] text-[var(--down)]',
  work: 'border-[var(--accent)] text-[var(--accent)]',
  flat: 'border-slate-600 text-slate-300',
  halt: 'border-[var(--down)] text-[var(--down)]',
}

/** Bottom-center transient confirmation pill. */
export function TerminalToast({ toast }: { toast: ToastMessage }) {
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-50 -translate-x-1/2">
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg border bg-slate-900/95 px-3.5 py-2 font-mono text-[12px] shadow-xl backdrop-blur',
          TONE_BY_KIND[toast.kind] ?? 'border-slate-700 text-slate-200',
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        {toast.text}
      </div>
    </div>
  )
}
