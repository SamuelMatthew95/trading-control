import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import { TONE_BADGE, TONE_BADGE_OUTLINED, type Tone } from '@/lib/design/sentiment'

export type BadgeVariant = 'soft' | 'outlined'
export type BadgeSize = 'xs' | 'sm'

const SIZE_CLASS: Record<BadgeSize, string> = {
  xs: 'px-1.5 py-0.5 text-3xs font-semibold',
  sm: 'px-2 py-0.5 text-xs font-medium',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
  variant?: BadgeVariant
  size?: BadgeSize
  /** Fully rounded pill shape instead of the default rounded rectangle. */
  pill?: boolean
}

/**
 * Canonical badge/chip — colour always routes through the Tone maps
 * (TONE_BADGE / TONE_BADGE_OUTLINED); never re-declare a chip colour recipe
 * at a call site. Compose extras (font-mono, tabular-nums) via className.
 */
export function Badge({
  tone = 'neutral',
  variant = 'soft',
  size = 'sm',
  pill = false,
  className,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1',
        pill ? 'rounded-full' : 'rounded',
        variant === 'outlined' ? `border ${TONE_BADGE_OUTLINED[tone]}` : TONE_BADGE[tone],
        SIZE_CLASS[size],
        className,
      )}
      {...props}
    />
  )
}
