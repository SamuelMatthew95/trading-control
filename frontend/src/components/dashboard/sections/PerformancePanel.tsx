'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone, type Tone } from '@/lib/state'
import { formatRatioAsPercent, formatSignedCurrency } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type { PerformanceSummary } from '@/stores/useCodexStore'

interface PerformancePanelProps {
  summary: PerformanceSummary | null | undefined
}

interface Cell {
  label: string
  value: string
  tone: Tone
}

export function PerformancePanel({ summary }: PerformancePanelProps) {
  const cells: Cell[] = summary
    ? [
        {
          label: 'Total P&L',
          value: formatSignedCurrency(summary.total_pnl),
          tone: getNumberTone(summary.total_pnl),
        },
        {
          label: 'Win Rate',
          value: formatRatioAsPercent(summary.win_rate, 1),
          tone: 'muted',
        },
        {
          label: 'Best Trade',
          value: formatSignedCurrency(summary.best_trade),
          tone: 'pos',
        },
        {
          label: 'Worst Trade',
          value: formatSignedCurrency(summary.worst_trade),
          tone: 'neg',
        },
      ]
    : (['Total P&L', 'Win Rate', 'Best Trade', 'Worst Trade'] as const).map((label) => ({
        label,
        value: '—',
        tone: 'muted' as const,
      }))

  return (
    <TerminalCard>
      <SectionHeader title="Performance" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cells.map((cell) => (
          <div
            key={cell.label}
            className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800"
          >
            <p className={UI_TEXT.label}>{cell.label}</p>
            <p
              className={cn(
                'mt-1 text-sm font-mono tabular-nums font-semibold',
                cell.tone === 'muted'
                  ? 'text-slate-900 dark:text-slate-100'
                  : TONE_CLASSES[cell.tone].text,
              )}
            >
              {cell.value}
            </p>
          </div>
        ))}
      </div>
    </TerminalCard>
  )
}
