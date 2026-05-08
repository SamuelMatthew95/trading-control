'use client'

import { TrendingDown, TrendingUp } from 'lucide-react'
import { MetricTile } from '@/components/terminal'
import { getNumberTone } from '@/lib/state'
import { formatNumber, formatSignedCurrency, formatSignedPercent } from '@/lib/format'
import type { DashboardSummaryView } from '@/lib/types'

const TOP_METRICS_GRID = 'grid grid-cols-2 gap-4 sm:grid-cols-4'

interface TopMetricsRowProps {
  summary: DashboardSummaryView
}

export function TopMetricsRow({ summary }: TopMetricsRowProps) {
  const dailyChangeTone = getNumberTone(summary.dailyChange)
  const dailyPnlTone = getNumberTone(summary.dailyPnlNumeric)

  return (
    <div className={TOP_METRICS_GRID}>
      <MetricTile
        label="Daily P&L"
        value={summary.hasOrders ? formatSignedCurrency(summary.dailyPnlNumeric) : '—'}
        icon={summary.dailyPnlNumeric > 0 ? TrendingUp : summary.dailyPnlNumeric < 0 ? TrendingDown : undefined}
        tone={dailyPnlTone === 'muted' ? undefined : dailyPnlTone}
      />
      <MetricTile
        label="Win Rate"
        value={
          summary.winRate == null || !Number.isFinite(summary.winRate)
            ? '—'
            : `${summary.winRate.toFixed(2)}%${summary.hasClosedTrades ? '' : ' (open only)'}`
        }
      />
      <MetricTile
        label="Active Positions"
        value={formatNumber(summary.activePositions)}
      />
      <MetricTile
        label="Daily Change %"
        value={summary.dailyChange != null ? formatSignedPercent(summary.dailyChange) : '0.00%'}
        tone={dailyChangeTone === 'muted' ? undefined : dailyChangeTone}
        icon={summary.dailyChange != null && summary.dailyChange > 0 ? TrendingUp : summary.dailyChange != null && summary.dailyChange < 0 ? TrendingDown : undefined}
      />
    </div>
  )
}
