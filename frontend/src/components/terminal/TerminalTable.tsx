import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { UI_TEXT } from '@/lib/constants/ui'

interface TerminalTableProps {
  /** Column headers in display order. */
  headers: readonly string[]
  children: ReactNode
  className?: string
  /** Right-align specific columns (0-indexed). */
  rightAlignedColumns?: readonly number[]
}

/**
 * Standard dense data table — uppercase mono headers, divider rows.
 * Prefer this over hand-rolling `<table>` markup with verbose Tailwind chains.
 */
export function TerminalTable({
  headers,
  children,
  className,
  rightAlignedColumns = [],
}: TerminalTableProps) {
  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-slate-200 dark:border-slate-800">
            {headers.map((head, idx) => (
              <th
                key={head}
                className={cn(
                  UI_TEXT.label,
                  'px-2 py-2 font-semibold tracking-widest',
                  rightAlignedColumns.includes(idx) ? 'text-right' : 'text-left',
                )}
              >
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

export interface TerminalRowProps {
  children: ReactNode
  className?: string
  onClick?: () => void
}

export function TerminalRow({ children, className, onClick }: TerminalRowProps) {
  return (
    <tr
      onClick={onClick}
      className={cn(
        'border-t border-slate-200 dark:border-slate-800',
        onClick && 'cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800/50',
        className,
      )}
    >
      {children}
    </tr>
  )
}

export interface TerminalCellProps {
  children: ReactNode
  className?: string
  align?: 'left' | 'right' | 'center'
  numeric?: boolean
  /** Apply default cell padding. Set false when wrapping a complex child. */
  padded?: boolean
  colSpan?: number
}

export function TerminalCell({
  children,
  className,
  align = 'left',
  numeric = false,
  padded = true,
  colSpan,
}: TerminalCellProps) {
  return (
    <td
      colSpan={colSpan}
      className={cn(
        padded && 'px-2 py-2',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        numeric ? UI_TEXT.cell : 'text-sm text-slate-900 dark:text-slate-100',
        className,
      )}
    >
      {children}
    </td>
  )
}
