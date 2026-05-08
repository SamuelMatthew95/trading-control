'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { SPLIT_GRID, STACK } from '@/lib/styles'
import { TopMetricsRow } from './TopMetricsRow'
import { PerformancePanel } from './PerformancePanel'
import { AgentMatrix } from './AgentMatrix'
import { LiveMarketPrices } from './LiveMarketPrices'
import type { Order, PerformanceSummary, PriceData } from '@/stores/useCodexStore'
import type { AgentSummary, DashboardSummaryView } from '@/lib/types'

interface OverviewSectionProps {
  summary: DashboardSummaryView
  performanceSummary: PerformanceSummary | null
  orders: Order[]
  agents: AgentSummary[]
  prices: Record<string, PriceData>
  pricesLoading: boolean
  wsConnected: boolean
}

export function OverviewSection({
  summary,
  performanceSummary,
  orders,
  agents,
  prices,
  pricesLoading,
  wsConnected,
}: OverviewSectionProps) {
  return (
    <div className={STACK}>
      <TopMetricsRow summary={summary} />
      <PerformancePanel summary={performanceSummary} />

      <div className={SPLIT_GRID}>
        <TerminalCard className="sm:col-span-2 lg:col-span-2">
          <SectionHeader title="Equity Curve" />
          <EquityCurve orders={orders} />
        </TerminalCard>
        <AgentMatrix
          agents={agents}
          wsConnected={wsConnected}
          className="sm:col-span-2 lg:col-span-2"
        />
      </div>

      <LiveMarketPrices prices={prices} loading={pricesLoading} />
    </div>
  )
}
