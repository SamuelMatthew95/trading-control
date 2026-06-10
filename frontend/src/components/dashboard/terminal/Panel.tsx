'use client'

import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Terminal panel shell — theme-aware so light and dark both read cleanly:
 * white / slate-900 surface, slate-200 / slate-800 border, a fixed-height
 * header (`--term-hdr`) with an uppercase label, optional right slot + count pill.
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
        // h-full pins the panel to its wrapper's height so the scrollable body
        // actually scrolls — content-sized panels overflowed their grid track
        // and painted over the panel below them.
        'flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900',
        className,
      )}
    >
      {title != null && (
        <header className="flex h-[var(--term-hdr)] shrink-0 items-center justify-between border-b border-slate-200 px-3 dark:border-slate-800">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{title}</p>
          <div className="flex items-center gap-2">
            {right}
            {count != null && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-500 dark:bg-slate-800 dark:text-slate-400">
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
