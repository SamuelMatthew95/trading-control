'use client'

import { Activity, Brain, FileCode, Zap } from 'lucide-react'
import { TerminalCard, SectionHeader, MetricTile } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone } from '@/lib/state'
import { canonicalAgentKey } from '@/lib/constants/agentStates'
import { formatNumber, formatPercent, formatSignedCurrency, formatTimestamp } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import {
  INNER_TILE,
  METRIC_ROW_GRID_LG,
  STACK,
  STRONG_MONO,
} from '@/lib/styles'

const EMPTY_PROPOSALS_BANNER =
  'rounded-[6px] border border-slate-200 bg-slate-100/50 p-3 dark:border-slate-800 dark:bg-slate-900/60'
import { LearningPipelineStatusPanel } from './LearningPipelineStatusPanel'
import { ProposalsFeed } from './ProposalsFeed'
import { IcWeightsPanel } from './IcWeightsPanel'
import { GradeHistoryPanel } from './GradeHistoryPanel'
import type { GradeRecord } from '@/lib/api'
import type {
  PerformanceSummary,
  Proposal,
  ProposalStatus,
} from '@/stores/useCodexStore'
import type {
  AgentSummary,
  DashboardSummaryView,
  LearningSummaryView,
  PipelineStageView,
} from '@/lib/types'

interface LearningSectionProps {
  pipelineStages: readonly PipelineStageView[]
  learningSummary: LearningSummaryView
  proposals: Proposal[]
  onUpdateProposalStatus: (id: string, status: ProposalStatus) => void
  icWeights: Record<string, number>
  gradeHistory: GradeRecord[]
  resolvedPerformanceSummary: PerformanceSummary | null
  summary: DashboardSummaryView
  agents: AgentSummary[]
}

export function LearningSection({
  pipelineStages,
  learningSummary,
  proposals,
  onUpdateProposalStatus,
  icWeights,
  gradeHistory,
  resolvedPerformanceSummary,
  summary,
  agents,
}: LearningSectionProps) {
  const reflectionAgentStatus =
    agents.find((a) => canonicalAgentKey(a.name) === 'REFLECTION_AGENT')?.status ?? 'Unknown'
  const totalPnlTone = getNumberTone(resolvedPerformanceSummary?.total_pnl)

  return (
    <div className={STACK}>
      <LearningPipelineStatusPanel stages={pipelineStages} />

      <div className={METRIC_ROW_GRID_LG}>
        <MetricTile
          label="Trades Evaluated"
          value={formatNumber(learningSummary.tradesEvaluated)}
          icon={FileCode}
        />
        <MetricTile
          label="Reflections Completed"
          value={formatNumber(learningSummary.reflectionsCompleted)}
          icon={Brain}
        />
        <MetricTile
          label="IC Values Updated"
          value={formatNumber(learningSummary.icValuesUpdated)}
          icon={Activity}
        />
        <MetricTile
          label="Strategies Tested"
          value={formatNumber(learningSummary.strategiesTested)}
          icon={Zap}
        />
      </div>

      <ProposalsFeed proposals={proposals} onUpdateStatus={onUpdateProposalStatus} />
      {proposals.length === 0 ? (
        <p className={cn(UI_TEXT.muted, EMPTY_PROPOSALS_BANNER)}>
          No strategy proposals yet. Reflection pipeline may be idle, disconnected, or awaiting graded trades.
        </p>
      ) : null}

      <IcWeightsPanel weights={icWeights} />

      <GradeHistoryPanel grades={gradeHistory} />

      <TerminalCard>
        <SectionHeader title="Performance Summary" />
        <div className={METRIC_ROW_GRID_LG}>
          <SummaryTile
            label="Win Rate"
            value={summary.winRate == null ? '—' : formatPercent(summary.winRate)}
          />
          <SummaryTile
            label="Total P&L"
            value={formatSignedCurrency(resolvedPerformanceSummary?.total_pnl)}
            valueClassName={TONE_CLASSES[totalPnlTone].text}
          />
          <SummaryTile
            label="Best Day"
            value={
              learningSummary.bestDay
                ? `${learningSummary.bestDay[0]} (${formatSignedCurrency(learningSummary.bestDay[1])})`
                : 'N/A'
            }
            valueClassName={TONE_CLASSES.pos.text}
          />
          <SummaryTile
            label="Worst Day"
            value={
              learningSummary.worstDay
                ? `${learningSummary.worstDay[0]} (${formatSignedCurrency(learningSummary.worstDay[1])})`
                : 'N/A'
            }
            valueClassName={TONE_CLASSES.neg.text}
          />
        </div>
      </TerminalCard>

      <TerminalCard>
        <SectionHeader title="Learning Runtime Notes" />
        <p className={UI_TEXT.muted}>
          Reflection agent status:{' '}
          <span className={STRONG_MONO}>{reflectionAgentStatus}</span>
        </p>
        <p className={cn(UI_TEXT.muted, 'mt-1')}>
          Last grade timestamp:{' '}
          <span className={STRONG_MONO}>
            {gradeHistory[0]?.timestamp ? formatTimestamp(gradeHistory[0].timestamp) : 'No grades yet'}
          </span>
        </p>
      </TerminalCard>
    </div>
  )
}

interface SummaryTileProps {
  label: string
  value: string
  valueClassName?: string
}

function SummaryTile(props: SummaryTileProps) {
  const valueClass = props.valueClassName ?? 'text-slate-900 dark:text-slate-100'
  return (
    <div className={INNER_TILE}>
      <p className={UI_TEXT.muted}>{props.label}</p>
      <p className={cn('text-sm font-mono tabular-nums', valueClass)}>{props.value}</p>
    </div>
  )
}
