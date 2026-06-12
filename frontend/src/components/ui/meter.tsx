import { cn } from '@/lib/utils'

export interface MeterProps {
  /** Fill amount, 0–100 (clamped). */
  value: number
  /** Accessible name for the bar. */
  label?: string
  className?: string
  /** Fill colour override — route through a Tone/token class (e.g. TONE_DOT). */
  fillClassName?: string
}

/**
 * Canonical progress/meter bar.
 *
 * The fill width is live data, which Tailwind's static class extraction
 * cannot express — so this component owns the single sanctioned inline
 * `style` in the codebase (enforced by the design-system guardrail test).
 * Never write `style={{ width: … }}` anywhere else; render a Meter.
 */
export function Meter({ value, label, className, fillClassName }: MeterProps) {
  const pct = Math.min(100, Math.max(0, value))
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label={label}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-muted-foreground/15', className)}
    >
      <div
        className={cn('h-full rounded-full bg-brand transition-all', fillClassName)}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
