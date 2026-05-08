import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TONE_CLASSES } from '@/lib/state'
import { UI_RADIUS } from '@/lib/constants/ui'

interface ErrorStateProps {
  message: string
  /** Optional sub-detail (e.g. status code, hint). */
  detail?: string
  className?: string
}

/**
 * Visible error surface for panels that failed to load. Distinct from EmptyState
 * — empty means "no data yet"; error means "we tried and it failed". Both are
 * preserved in the UI; never hide a backend failure to make the page look clean.
 */
export function ErrorState({ message, detail, className }: ErrorStateProps) {
  const tone = TONE_CLASSES.neg
  return (
    <div
      className={cn(
        'flex min-h-28 flex-col items-center justify-center gap-2 px-4 py-8',
        UI_RADIUS.card,
        tone.card,
        className,
      )}
    >
      <AlertTriangle className={cn('h-5 w-5', tone.text)} />
      <p className={cn('text-sm font-medium', tone.text)}>{message}</p>
      {detail ? <p className="text-xs text-slate-500">{detail}</p> : null}
    </div>
  )
}
