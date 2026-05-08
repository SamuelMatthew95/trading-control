import {
  INNER_TILE,
  ROW_BETWEEN,
  SKELETON_LABEL,
  SKELETON_VALUE,
  SKELETON_TINY,
  SKELETON_TINIER,
} from '@/lib/styles'
import { cn } from '@/lib/utils'

/** Loading placeholder shaped like a real price tile so the layout doesn't shift on hydration. */
export function PriceTileSkeleton() {
  return (
    <div className={INNER_TILE}>
      <div className={SKELETON_LABEL} />
      <div className={SKELETON_VALUE} />
      <div className={cn('mt-2', ROW_BETWEEN)}>
        <div className={SKELETON_TINY} />
        <div className={SKELETON_TINIER} />
      </div>
    </div>
  )
}
