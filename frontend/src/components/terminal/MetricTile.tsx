import type { ComponentType, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { UI_PAD, UI_RADIUS, UI_SURFACE, UI_TEXT } from '@/lib/constants/ui'

interface MetricTileProps {
  label: string
  value: ReactNode
  /** Optional small caption below the value. */
  hint?: ReactNode
  /** Right-aligned icon for context. */
  icon?: ComponentType<{ className?: string }>
  /** Color the value text by tone (default: neutral). */
  tone?: Tone
  /** Render the value at large size (use for top-of-page key metrics). */
  size?: 'sm' | 'lg'
  className?: string
}

/**
 * Single numeric metric block — small uppercase label, large mono value,
 * optional hint underneath. Use this in 2/3/4-column grids.
 */
export function MetricTile({
  label,
  value,
  hint,
  icon: Icon,
  tone,
  size = 'lg',
  className,
}: MetricTileProps) {
  const valueClass = tone ? TONE_CLASSES[tone].text : 'text-slate-950 dark:text-slate-100'
  const valueText =
    size === 'lg'
      ? UI_TEXT.metric
      : cn(UI_TEXT.cell, 'font-semibold')

  return (
    <div
      className={cn(
        UI_RADIUS.card,
        UI_SURFACE.card,
        UI_PAD.tile,
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className={UI_TEXT.label}>{label}</p>
        {Icon ? <Icon className="h-4 w-4 text-slate-500" /> : null}
      </div>
      <p className={cn(valueText, valueClass, 'mt-1')}>{value}</p>
      {hint != null ? <p className={cn(UI_TEXT.muted, 'mt-1')}>{hint}</p> : null}
    </div>
  )
}
