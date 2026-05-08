import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone } from '@/lib/state'
import { formatPnl } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'

interface PnlValueProps {
  value: number | null | undefined
  /** Optional percent (already in percent units, e.g. 5.5 for 5.5%). */
  percent?: number | null | undefined
  className?: string
}

/**
 * Centralized P&L display: signed currency, sign-derived tone, optional
 * trailing percent. Replaces every ad-hoc `+/-$X (Y%)` rendering in the app.
 */
export function PnlValue({ value, percent, className }: PnlValueProps) {
  const tone = getNumberTone(value)
  const pctSuffix =
    percent != null && Number.isFinite(percent)
      ? ` (${percent > 0 ? '+' : ''}${percent.toFixed(1)}%)`
      : ''
  return (
    <span className={cn(UI_TEXT.numeric, 'font-semibold text-sm', TONE_CLASSES[tone].text, className)}>
      {formatPnl(value)}
      {pctSuffix}
    </span>
  )
}
