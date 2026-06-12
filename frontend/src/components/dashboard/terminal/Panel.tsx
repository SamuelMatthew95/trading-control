'use client'

import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Terminal panel shell — card/popover surface tokens so light and dark both
 * read cleanly, a fixed-height header (`--term-hdr`) with an uppercase label,
 * optional right slot + count pill.
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
        'flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card dark:bg-popover',
        className,
      )}
    >
      {title != null && (
        <header className="flex h-[var(--term-hdr)] shrink-0 items-center justify-between border-b px-3">
          <p className="text-3xs font-semibold uppercase tracking-caps text-muted-foreground">{title}</p>
          <div className="flex items-center gap-2">
            {right}
            {count != null && (
              <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-3xs text-muted-foreground">
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
