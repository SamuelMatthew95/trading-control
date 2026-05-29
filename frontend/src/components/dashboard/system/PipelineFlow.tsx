'use client'

import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'

import { AGENT_REASONING } from '@/constants/agents'

import { PipelineStage } from './PipelineStage'
import { canonicalAgentKey } from './helpers'
import type { StageStatus } from './types'
import type { AgentStatus } from '@/stores/useCodexStore'

export interface PipelineFlowProps {
  hasMarketData: boolean
  marketStageCount: number
  signalsCount: number
  ordersCount: number
  executionsCount: number
  agentStatuses: AgentStatus[]
}

const isAgentActive = (status: string | undefined): boolean =>
  status === 'ACTIVE' || status === 'active'

const flowingOrIdle = (count: number): StageStatus => (count > 0 ? 'flowing' : 'idle')

export function PipelineFlow(props: PipelineFlowProps) {
  const {
    hasMarketData,
    marketStageCount,
    signalsCount,
    ordersCount,
    executionsCount,
    agentStatuses,
  } = props

  const reasoningAgent = agentStatuses.find(
    (a) => canonicalAgentKey(a.name) === AGENT_REASONING,
  )

  return (
    <div className={cardClass}>
      <div className="mb-4 flex items-center justify-between">
        <p className={sectionTitleClass}>Pipeline Flow</p>
        <p className={mutedClass}>
          Reasoning: <span className="font-mono">{reasoningAgent?.status ?? 'unknown'}</span>
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-y-3 overflow-x-auto pb-2">
        <PipelineStage
          label="Market"
          count={marketStageCount}
          status={hasMarketData ? 'live' : 'stalled'}
        />
        <PipelineStage label="Signals" count={signalsCount} status={flowingOrIdle(signalsCount)} />
        <PipelineStage
          label="Reasoning"
          count={reasoningAgent?.event_count ?? 0}
          status={isAgentActive(reasoningAgent?.status) ? 'flowing' : 'idle'}
        />
        <PipelineStage label="Orders" count={ordersCount} status={flowingOrIdle(ordersCount)} />
        <PipelineStage
          label="Executions"
          count={executionsCount}
          status={flowingOrIdle(executionsCount)}
          isLast
        />
      </div>
    </div>
  )
}
