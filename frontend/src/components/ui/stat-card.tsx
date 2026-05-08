import { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface StatCardProps {
  label: string
  value: ReactNode
  className?: string
  valueClassName?: string
}

export function StatCard({ label, value, className, valueClassName }: StatCardProps) {
  return (
    <div className={cn('rounded-lg border border-slate-200 p-3 dark:border-slate-800', className)}>
      <p className="text-xs font-sans text-slate-500 dark:text-slate-400">{label}</p>
      <p className={cn('text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100', valueClassName)}>{value}</p>
    </div>
  )
}
