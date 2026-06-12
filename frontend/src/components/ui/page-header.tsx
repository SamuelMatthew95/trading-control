import type { ReactNode } from 'react'
import { sectionTitleClass } from '@/lib/dashboard-styles'

export interface PageHeaderProps {
  /** Small uppercase kicker above the title. */
  eyebrow: string
  title: string
  description?: string
  /** Right-aligned slot (actions, status). */
  right?: ReactNode
}

/**
 * Canonical page heading — eyebrow, h1, description on a card surface.
 * Every dashboard section opens with this so pages share one heading rhythm.
 */
export function PageHeader({ eyebrow, title, description, right }: PageHeaderProps) {
  return (
    <section className="rounded-xl border bg-card px-3 py-3 shadow-card dark:bg-card/90">
      <p className={sectionTitleClass}>{eyebrow}</p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
          {description ? (
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {right}
      </div>
    </section>
  )
}
