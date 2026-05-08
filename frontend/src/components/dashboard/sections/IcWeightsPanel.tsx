'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'
import { ROW_BETWEEN, ROW_START, SECONDARY_TEXT, STACK_TIGHT } from '@/lib/styles'

interface IcWeightsPanelProps {
  weights: Record<string, number>
}

interface IcWeightRow {
  factor: string
  weight: number
}

const IC_BAR_TRACK = 'h-2 w-24 rounded-full bg-slate-200 dark:bg-slate-700'
const IC_BAR_FILL = 'h-2 rounded-full bg-slate-500'
const IC_VALUE_LABEL =
  'w-10 text-right text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300'
const IC_FACTOR_LABEL = 'text-sm ' + SECONDARY_TEXT

/**
 * Weight values come from Redis JSON with no server-side validation. Coerce
 * non-finite numbers to 0 and clamp into [0, 1] before rendering so the bar
 * never overflows.
 */
function clampWeight(value: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  if (value < 0) return 0
  if (value > 1) return 1
  return value
}

function toRows(weights: Record<string, number>): IcWeightRow[] {
  return Object.entries(weights).map(([factor, weight]) => ({
    factor,
    weight: clampWeight(weight),
  }))
}

function IcWeightBar(props: { row: IcWeightRow }) {
  const pct = Math.round(props.row.weight * 100)
  const barWidthStyle = { width: `${pct}%` }
  return (
    <div className={ROW_BETWEEN}>
      <span className={IC_FACTOR_LABEL}>{props.row.factor}</span>
      <div className={ROW_START}>
        <div className={IC_BAR_TRACK}>
          <div className={IC_BAR_FILL} style={barWidthStyle} />
        </div>
        <span className={IC_VALUE_LABEL}>{(props.row.weight * 100).toFixed(1)}%</span>
      </div>
    </div>
  )
}

export function IcWeightsPanel(props: IcWeightsPanelProps) {
  const rows = toRows(props.weights)
  if (rows.length === 0) return null
  return (
    <TerminalCard>
      <SectionHeader title="IC Factor Weights" />
      <div className={STACK_TIGHT}>
        {rows.map((row) => (
          <IcWeightBar key={row.factor} row={row} />
        ))}
      </div>
    </TerminalCard>
  )
}
