import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { UI_RADIUS } from '@/lib/constants/ui'

interface StatusChipProps {
  /** Visible label — kept short and uppercased. */
  label: string
  tone: Tone
  /** Render a small filled dot before the label. */
  dot?: boolean
  className?: string
  /** Compact mode for use inside tables. */
  size?: 'sm' | 'md'
}

/**
 * Compact uppercase status chip — the canonical way to display a state value.
 *
 * Color comes from the `tone`. Components must NEVER pick raw color classes;
 * they must always pass a Tone (look up via `toneFor*` helpers in lib/state).
 */
export function StatusChip({
  label,
  tone,
  dot = true,
  className,
  size = 'sm',
}: StatusChipProps) {
  const classes = TONE_CLASSES[tone]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 font-mono uppercase tracking-[0.04em]',
        UI_RADIUS.chip,
        classes.chip,
        size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs',
        className,
      )}
    >
      {dot ? <span className={cn('h-1.5 w-1.5 rounded-full', classes.bg)} aria-hidden /> : null}
      {label}
    </span>
  )
}
