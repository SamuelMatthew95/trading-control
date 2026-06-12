import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { cardClass, mutedClass, sectionTitleClass, valueClass } from '@/lib/dashboard-styles'

/**
 * Compact centered metric — value over label. The small sibling of StatTile
 * for dense grids inside modals/panels.
 */
export function MetricTile({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg border p-2 text-center">
      <p className="font-mono text-lg tabular-nums text-foreground">{value}</p>
      <p className={mutedClass}>{label}</p>
    </div>
  )
}

export interface StatTileProps {
  label: string
  value: ReactNode
  /** Optional adornment rendered opposite the label (icon, icon chip, badge). */
  icon?: ReactNode
  /** Extra classes for the value (size/tone overrides, e.g. `text-xl text-success`). */
  valueClassName?: string
  /** Muted context lines rendered under the value. */
  lines?: ReactNode[]
  align?: 'left' | 'center'
  className?: string
}

/**
 * Canonical KPI/stat tile — label, headline value, optional icon and context
 * lines. Every stat/metric tile composes this; never re-declare the
 * label-over-value recipe.
 */
export function StatTile({
  label,
  value,
  icon,
  valueClassName,
  lines = [],
  align = 'left',
  className,
}: StatTileProps) {
  return (
    <div className={cn(cardClass, align === 'center' && 'text-center', className)}>
      <div
        className={cn(
          'flex items-center gap-2',
          align === 'center' ? 'justify-center' : 'justify-between',
        )}
      >
        <p className={sectionTitleClass}>{label}</p>
        {icon}
      </div>
      <p className={cn(valueClass, 'mt-2', valueClassName)}>{value}</p>
      {lines.map((line, i) => (
        <p key={i} className={cn(mutedClass, 'mt-1 truncate')}>
          {line}
        </p>
      ))}
    </div>
  )
}
