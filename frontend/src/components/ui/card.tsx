import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'

export interface CardProps {
  /** Panel section label — rendered with the canonical section title style. */
  title?: ReactNode
  /** Right-aligned header content (count, status, actions). */
  right?: ReactNode
  className?: string
  children: ReactNode
}

/**
 * Canonical dashboard panel — `cardClass` surface plus the shared
 * title/meta header row. Compose this instead of re-declaring
 * `rounded-xl border bg-… p-…` containers.
 */
export function Card({ title, right, className, children }: CardProps) {
  return (
    <section className={cn(cardClass, className)}>
      {(title != null || right != null) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {typeof title === 'string' ? <h2 className={sectionTitleClass}>{title}</h2> : title}
          {right}
        </div>
      )}
      {children}
    </section>
  )
}
