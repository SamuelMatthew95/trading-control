'use client'

import { useEffect, useState } from 'react'
import { WifiOff, X } from 'lucide-react'

import { cardClass } from '@/lib/dashboard-styles'
import { formatClockHMS } from '@/lib/formatters'
import { UI_COPY } from '@/constants/copy'
import { Button } from '@/components/ui/button'

/**
 * Warning strip shown while `/dashboard/state` is unreachable but the store
 * still holds previously-loaded data. The store is never wiped on a failed
 * fetch, so the panels behind this banner keep rendering last-known values
 * instead of blanking — this strip just makes the staleness explicit.
 *
 * Owns its dismissal: the X hides it for the CURRENT outage only, and a
 * recovery (active → false) re-arms it for the next one. Self-contained so
 * call sites stay a single stateless line.
 */
export function BackendOfflineBanner({
  active,
  lastKnownAt,
}: {
  /** True while the backend is unreachable AND there is last-known data to show. */
  active: boolean
  /** ISO timestamp of the last successful hydration (clock-labelled in the copy). */
  lastKnownAt: string | null
}) {
  const [dismissed, setDismissed] = useState(false)
  useEffect(() => {
    // Re-arm the banner for the next outage once the backend recovers.
    if (!active) setDismissed(false)
  }, [active])
  if (!active || dismissed) return null

  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs font-semibold text-warning"
      role="alert"
    >
      <WifiOff className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="flex-1">
        {UI_COPY.backendOffline.bannerPrefix} ({formatClockHMS(lastKnownAt)})
      </span>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => setDismissed(true)}
        aria-label={UI_COPY.backendOffline.dismissAria}
        className="h-5 w-5 text-warning hover:bg-warning/20 hover:text-warning"
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

/**
 * Full-panel explanation for the worst case: backend unreachable AND nothing
 * was ever loaded this session, so there is no last-known data to fall back
 * on. Replaces the section content — empty panels otherwise read as
 * "everything is broken".
 */
export function BackendOfflineEmptyState() {
  return (
    <div className={cardClass}>
      <div className="flex min-h-48 flex-col items-center justify-center gap-3 px-4 py-12 text-center">
        <WifiOff className="h-8 w-8 text-muted-foreground/40" aria-hidden />
        <p className="text-sm font-semibold text-foreground/80">{UI_COPY.backendOffline.emptyTitle}</p>
        <p className="max-w-md text-xs leading-5 text-muted-foreground">
          {UI_COPY.backendOffline.emptyBody}
        </p>
      </div>
    </div>
  )
}
