import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { FALLBACK_TEXT } from '@/utils/a11yFormatters'

export function SectionCard({
  title,
  right,
  children,
  className,
  titleAs = 'h2',
}: {
  title: string
  right?: ReactNode
  children: ReactNode
  className?: string
  titleAs?: 'h2' | 'h3'
}) {
  const Heading = titleAs
  return (
    <section className={cn('rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:p-5', className)}>
      <header className="mb-3 flex items-center justify-between gap-2">
        <Heading className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">{title}</Heading>
        {right}
      </header>
      {children}
    </section>
  )
}

export function AccessibleTime({ value, fallback = FALLBACK_TEXT.missingTimestamp }: { value?: string | null; fallback?: string }) {
  if (!value) return <span>{fallback}</span>
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return <span>{fallback}</span>
  return <time dateTime={date.toISOString()}>{date.toLocaleString()}</time>
}

export function TraceButton({
  traceId,
  onOpen,
  context,
}: {
  traceId: string
  onOpen: (traceId: string) => void
  context: string
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(traceId)}
      aria-label={`Open ${context} trace ${traceId}`}
      className="rounded px-1.5 py-0.5 text-[10px] font-mono text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
    >
      trace:{traceId.slice(0, 8)}
    </button>
  )
}
