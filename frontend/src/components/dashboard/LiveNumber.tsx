'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type FlashDirection = 'up' | 'down'

export interface LiveNumberProps {
  /** Numeric value used only for change detection. null/undefined never flashes. */
  value: number | null | undefined
  /** Already-formatted display content (e.g. "$50,000.00"). */
  children: ReactNode
  className?: string
  /** How long the highlight lingers before fading out. */
  flashMs?: number
}

/**
 * Wraps a formatted number and briefly flashes a green/red highlight whenever
 * the underlying numeric `value` changes, so live updates are *visible* instead
 * of silently swapping in place — the difference between "is this thing even
 * updating?" and watching P&L move. Direction drives the colour (up→success,
 * down→danger) via the shared design tokens, and the highlight fades through a
 * CSS transition. Horizontal padding is offset with a negative margin so the
 * flash never nudges surrounding layout.
 */
export function LiveNumber({ value, children, className, flashMs = 700 }: LiveNumberProps) {
  const previous = useRef<number | null | undefined>(value)
  const [flash, setFlash] = useState<FlashDirection | null>(null)

  useEffect(() => {
    const prior = previous.current
    previous.current = value
    if (typeof value !== 'number' || typeof prior !== 'number' || value === prior) return
    setFlash(value > prior ? 'up' : 'down')
    const timer = setTimeout(() => setFlash(null), flashMs)
    return () => clearTimeout(timer)
  }, [value, flashMs])

  return (
    <span
      data-flash={flash ?? undefined}
      className={cn(
        '-mx-1 rounded px-1 transition-colors duration-700',
        flash === 'up' && 'bg-success/20',
        flash === 'down' && 'bg-danger/20',
        className,
      )}
    >
      {children}
    </span>
  )
}

export interface LiveDotProps {
  live: boolean
  label?: string
  className?: string
}

/**
 * Small pulsing status dot — green + ping animation when the feed is live, muted
 * and still when it is not. Signals at a glance that the numbers beside it are
 * streaming rather than stale.
 */
export function LiveDot({ live, label = 'Live', className }: LiveDotProps) {
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <span className="relative flex h-1.5 w-1.5">
        {live && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-70" />
        )}
        <span
          className={cn(
            'relative inline-flex h-1.5 w-1.5 rounded-full',
            live ? 'bg-success' : 'bg-muted-foreground',
          )}
        />
      </span>
      <span
        className={cn(
          'text-[10px] font-mono uppercase tracking-wide',
          live ? 'text-success' : 'text-muted-foreground',
        )}
      >
        {label}
      </span>
    </span>
  )
}
