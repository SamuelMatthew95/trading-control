'use client'

import type { ReactNode } from 'react'

import { cardClass, sectionTitleClass, valueClass, mutedClass } from '@/lib/dashboard-styles'

export interface KpiCardProps {
  label: string
  value: ReactNode
  /** Muted context lines rendered under the value. */
  lines?: ReactNode[]
}

/** A single headline metric: label, big value, and optional context lines. */
export function KpiCard({ label, value, lines = [] }: KpiCardProps) {
  return (
    <div className={cardClass}>
      <p className={sectionTitleClass}>{label}</p>
      <p className={valueClass}>{value}</p>
      {lines.map((line, index) => (
        <p key={index} className={mutedClass}>
          {line}
        </p>
      ))}
    </div>
  )
}
