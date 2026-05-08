import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'

interface StateIndicatorProps {
  tone: Tone
  label?: string
  className?: string
  /** Pulse animation for live / pending states. */
  pulse?: boolean
}

/**
 * Tiny dot + optional label. Use this as a leading status marker when a full
 * StatusChip would feel too heavy (e.g. inside dense rows or beside titles).
 */
export function StateIndicator({ tone, label, className, pulse = false }: StateIndicatorProps) {
  const classes = TONE_CLASSES[tone]
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span
        className={cn('h-2 w-2 rounded-full', classes.bg, pulse && 'animate-pulse')}
        aria-hidden
      />
      {label ? (
        <span className={cn('text-xs font-mono uppercase tracking-[0.04em]', classes.text)}>
          {label}
        </span>
      ) : null}
    </span>
  )
}
