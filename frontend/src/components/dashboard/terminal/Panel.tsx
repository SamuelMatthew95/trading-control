'use client'

import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Terminal panel shell — the visual DNA shared by every terminal surface:
 * `rounded-xl border border-slate-800 bg-slate-900`, a fixed-height header
 * (`--term-hdr`) with an uppercase label, optional right slot, and a count pill.
 */
export function Panel({
  title,
  count,
  right,
  children,
  className,
  bodyClass,
}: {
  title?: ReactNode
  count?: number | string | null
  right?: ReactNode
  children: ReactNode
  className?: string
  bodyClass?: string
}) {
  return (
    <section
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900',
        className,
      )}
    >
      {title != null && (
        <header className="flex h-[var(--term-hdr)] shrink-0 items-center justify-between border-b border-slate-800 px-3">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">{title}</p>
          <div className="flex items-center gap-2">
            {right}
            {count != null && (
              <span className="rounded-full bg-slate-800 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                {count}
              </span>
            )}
          </div>
        </header>
      )}
      <div className={cn('min-h-0 flex-1', bodyClass)}>{children}</div>
    </section>
  )
}
