'use client'

import { useMemo } from 'react'

import { AgentObservability } from './AgentObservability'
import { ConnectionDiagnostics } from './ConnectionDiagnostics'
import { HeroMetrics } from './HeroMetrics'
import { PersistedHistory } from './PersistedHistory'
import { PipelineFlow } from './PipelineFlow'
import { PnlClarity } from './PnlClarity'
import { RecentEvents } from './RecentEvents'
import { StreamActivity } from './StreamActivity'
import { SystemAlerts } from './SystemAlerts'
import { computePipeline } from './helpers'
import type { SystemDashboardProps } from './types'

const isPersistenceEnabled = (props: SystemDashboardProps): boolean =>
  props.isInMemoryMode ||
  props.persistedCounts.length > 0 ||
  props.persistedEvents.length > 0 ||
  props.persistedLogs.length > 0 ||
  props.apiHealth.eventHistory === 'ok'

export function SystemDashboard(props: SystemDashboardProps) {
  const pipeline = useMemo(
    () =>
      computePipeline({
        streamStats: props.streamStats,
        recentEvents: props.recentEvents,
        wsLastMessageTimestamp: props.wsLastMessageTimestamp,
        wsMessageRate: props.wsDiagnostics.messageRate,
      }),
    [
      props.streamStats,
      props.recentEvents,
      props.wsLastMessageTimestamp,
      props.wsDiagnostics.messageRate,
    ],
  )

  const persistenceEnabled = isPersistenceEnabled(props)

  return (
    <div className="space-y-6">
      <HeroMetrics
        pipelineStatus={pipeline.pipelineStatus}
        marketStageCount={pipeline.marketStageCount}
        effectiveLatencyMs={pipeline.effectiveLatencyMs}
        throughput={pipeline.throughput}
        wsConnected={props.wsConnected}
        wsMessageCount={props.wsMessageCount}
        wsDiagnostics={props.wsDiagnostics}
        isInMemoryMode={props.isInMemoryMode}
        apiHealth={props.apiHealth}
        llmAvailable={props.llmAvailable}
        llmProvider={props.llmProvider}
      />
      <SystemAlerts
        pipelineWarning={pipeline.pipelineWarning}
        hasMarketData={pipeline.hasMarketData}
        latestMarketTickTs={pipeline.latestMarketTickTs}
        systemFeedError={props.systemFeedError}
        persistenceEnabled={persistenceEnabled}
        llmAvailable={props.llmAvailable}
        llmProvider={props.llmProvider}
      />
      <PipelineFlow
        hasMarketData={pipeline.hasMarketData}
        marketStageCount={pipeline.marketStageCount}
        signalsCount={pipeline.signalsCount}
        ordersCount={pipeline.ordersCount}
        executionsCount={pipeline.executionsCount}
        agentStatuses={props.agentStatuses}
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ConnectionDiagnostics
          wsConnected={props.wsConnected}
          wsLastMessageTimestamp={props.wsLastMessageTimestamp}
          wsDiagnostics={props.wsDiagnostics}
          throughput={pipeline.throughput}
          pricesCount={Object.keys(props.prices).length}
          pricesFetched={props.pricesFetched}
          apiHealth={props.apiHealth}
        />
        <StreamActivity streamStats={props.streamStats} />
      </div>
      <PnlClarity
        tradeFeed={props.tradeFeed}
        positions={props.positions}
        resolvedPerformanceSummary={props.resolvedPerformanceSummary}
      />
      <AgentObservability agentStatuses={props.agentStatuses} />
      <RecentEvents events={props.recentEvents} wsConnected={props.wsConnected} />
      <PersistedHistory
        isInMemoryMode={props.isInMemoryMode}
        persistedCounts={props.persistedCounts}
        persistedEvents={props.persistedEvents}
        persistedLogs={props.persistedLogs}
        onSelectTrace={props.setActiveTraceId}
      />
    </div>
  )
}
