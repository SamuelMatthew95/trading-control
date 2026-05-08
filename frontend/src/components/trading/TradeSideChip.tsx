import { StatusChip } from '@/components/terminal'
import { toneForTradeSide } from '@/lib/state'

interface TradeSideChipProps {
  side: string | null | undefined
  className?: string
}

/**
 * Standard chip for buy/sell/long/short — color & label come from a single
 * source so the dashboard can never disagree with the trading page.
 */
export function TradeSideChip({ side, className }: TradeSideChipProps) {
  const label = String(side ?? '').toUpperCase() || 'N/A'
  const tone = toneForTradeSide(side)
  return <StatusChip label={label} tone={tone} dot={false} className={className} />
}
