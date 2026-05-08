'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone, type Tone } from '@/lib/state'
import { formatRatioAsPercent, formatSignedCurrency } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { INNER_TILE, METRIC_ROW_GRID_2, PRIMARY_TEXT } from '@/lib/styles'
import type { PerformanceSummary } from '@/stores/useCodexStore'

interface PerformancePanelProps {
  summary: PerformanceSummary | null | undefined
}

interface PerformanceCell {
  label: string
  value: string
  tone: Tone
}

const EMPTY_CELLS: PerformanceCell[] = [
  { label: 'Total P&L', value: '—', tone: 'muted' },
  { label: 'Win Rate', value: '—', tone: 'muted' },
  { label: 'Best Trade', value: '—', tone: 'muted' },
  { label: 'Worst Trade', value: '—', tone: 'muted' },
]

function buildCells(summary: PerformanceSummary): PerformanceCell[] {
  return [
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
}

function valueClassFor(tone: Tone): string {
  if (tone === 'muted') return PRIMARY_TEXT
  return TONE_CLASSES[tone].text
}

function PerformanceTile(props: { cell: PerformanceCell }) {
  const { cell } = props
  return (
    <div className={INNER_TILE}>
      <p className={UI_TEXT.label}>{cell.label}</p>
      <p className={cn('mt-1 text-sm font-mono tabular-nums font-semibold', valueClassFor(cell.tone))}>
        {cell.value}
      </p>
    </div>
  )
}

export function PerformancePanel(props: PerformancePanelProps) {
  const cells = props.summary ? buildCells(props.summary) : EMPTY_CELLS
  return (
    <TerminalCard>
      <SectionHeader title="Performance" />
      <div className={METRIC_ROW_GRID_2}>
        {cells.map((cell) => (
          <PerformanceTile key={cell.label} cell={cell} />
        ))}
      </div>
    </TerminalCard>
  )
}
