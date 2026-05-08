import type { ComponentType, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { UI_TEXT } from '@/lib/constants/ui'

interface SectionHeaderProps {
  title: string
  icon?: ComponentType<{ className?: string }>
  /** Right-aligned content slot for counts, badges, controls. */
  right?: ReactNode
  className?: string
}

/**
 * Standard section title row: small uppercase mono label + optional icon
 * + optional right-aligned slot for counts / chips / actions.
 */
export function SectionHeader({ title, icon: Icon, right, className }: SectionHeaderProps) {
  return (
    <div className={cn('mb-3 flex items-center justify-between gap-2', className)}>
      <div className="flex min-w-0 items-center gap-2">
        {Icon ? <Icon className="h-4 w-4 text-slate-500" /> : null}
        <p className={cn(UI_TEXT.label, 'truncate')}>{title}</p>
      </div>
      {right ? <div className="flex shrink-0 items-center gap-2">{right}</div> : null}
    </div>
  )
}
