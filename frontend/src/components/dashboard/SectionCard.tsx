import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { FALLBACK_TEXT } from '@/utils/displayFormatters'
import { SectionHeader, TerminalCard } from '@/components/primitives/TerminalCard'

export function SectionCard({
  title,
  right,
  children,
  className,
}: {
  title: string
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <TerminalCard className={cn('p-4 sm:p-5', className)}>
      <SectionHeader title={title} meta={right} />
      {children}
    </TerminalCard>
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
