'use client'

import { useEffect, useState } from 'react'

import {
  useCodexStore,
  type AgentInstance,
  type AgentLog,
  type AgentStatus,
  type Notification,
  type Proposal,
  type RecentEvent,
  type StreamStat,
} from '@/stores/useCodexStore'
import type { ApiHealth, DecisionStats } from '@/hooks/useRestPoll'
import type { AgentSummary } from '@/lib/agent-pipeline'
import { parseTimestampMs, sanitizeValue } from '@/lib/formatters'
import { buildActivityTimeline } from '@/lib/activity-timeline'
import { countRecentNotifications, lastNotificationLabel } from '@/lib/notification-metrics'
import { STREAM_MARKET_EVENTS, STREAM_MARKET_TICKS } from '@/constants/streams'
import { AgentPipeline } from '@/components/dashboard/AgentPipeline'
import { LLMHealthPanel } from '@/components/dashboard/LLMHealthPanel'
import { LearningLoopPanel } from '@/components/dashboard/LearningLoopPanel'
import { ToolGovernancePanel } from '@/components/dashboard/ToolGovernancePanel'
import { PromptEvolutionPanel } from '@/components/dashboard/PromptEvolutionPanel'
import { LiveReasoningPanel } from '@/components/dashboard/LiveReasoningPanel'
import { RecentDecisionsPanel } from '@/components/dashboard/RecentDecisionsPanel'
import { NotificationFeed } from '@/components/dashboard/NotificationFeed'
import { ActivityTimeline } from './ActivityTimeline'
import { KpiCard } from './KpiCard'
import { AgentStatusTable } from './AgentStatusTable'
import { AgentScorecards } from './AgentScorecards'
import { SystemDiagnostics } from './SystemDiagnostics'
import { GroupLabel, type WiringFreshness } from './shared'

// Re-exported for backward compatibility (components/dashboard/agents/index.ts).
export type { WiringFreshness }

// ── Timing windows ──────────────────────────────────────────────────────────
const MARKET_LIVE_WINDOW_MS = 60_000
const NOTIFICATION_RECENT_WINDOW_MS = 3_600_000 // 1 hour
const AGENT_DATA_TIMEOUT_MS = 10_000

export interface AgentsDashboardProps {
  realAgents: AgentSummary[]
  wiringFreshness: WiringFreshness
  agentStatuses: AgentStatus[]
  agentInstances: AgentInstance[]
  agentLogs: AgentLog[]
  notifications: Notification[]
  proposals: Proposal[]
  decisionStats: DecisionStats | null
  recentDecisions: Array<Record<string, unknown>>
  recentEvents: RecentEvent[]
  apiHealth: ApiHealth
  marketTickCount: number
  lastMarketSymbol: string | null
  streamStats: Record<string, StreamStat>
  wsConnected: boolean
  isInMemoryMode: boolean
}

export function AgentsDashboard(props: AgentsDashboardProps) {
  const {
    realAgents,
    wiringFreshness,
    agentStatuses,
    agentInstances,
    agentLogs,
    notifications,
    proposals,
    decisionStats,
    recentDecisions,
    recentEvents,
    apiHealth,
    marketTickCount,
    lastMarketSymbol,
    streamStats,
    wsConnected,
    isInMemoryMode,
  } = props

  // One chronological story of what the pipeline is doing — built from the same
  // decisions, notifications, agent logs, and market events the panels below
  // show as state.
  const activityItems = buildActivityTimeline({ recentEvents, recentDecisions, notifications, agentLogs })

  // Only surface "no agents" after a grace period — agent data can arrive a beat
  // after the WebSocket connects.
  const [showNoAgentDataMessage, setShowNoAgentDataMessage] = useState(false)
  useEffect(() => {
    if (!wsConnected || realAgents.length > 0) {
      setShowNoAgentDataMessage(false)
      return
    }
    const timer = setTimeout(() => {
      const state = useCodexStore.getState()
      const hasAgentData =
        state.agentLogs.length > 0 || state.agentStatuses.length > 0 || state.agentInstances.length > 0
      if (!hasAgentData && state.wsConnected) setShowNoAgentDataMessage(true)
    }, AGENT_DATA_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [realAgents.length, wsConnected])

  const liveAgentCount = realAgents.filter((agent) => agent.status === 'Live').length
  const recentNotificationCount = countRecentNotifications(notifications, NOTIFICATION_RECENT_WINDOW_MS)

  const marketTs =
    streamStats?.[STREAM_MARKET_TICKS]?.lastMessageTimestamp ??
    streamStats?.[STREAM_MARKET_EVENTS]?.lastMessageTimestamp ??
    null
  const marketTsMs = parseTimestampMs(marketTs)
  const marketLive =
    marketTsMs != null ? Date.now() - marketTsMs < MARKET_LIVE_WINDOW_MS : marketTickCount > 0 && wsConnected

  // `decisionStats` may transiently be a partial `{}` while the first poll lands.
  const decisionHour = decisionStats?.last_hour
  const decisionsLastHour = decisionHour ? decisionHour.buys + decisionHour.sells + decisionHour.holds : null
  const decisionBreakdown = decisionHour
    ? `${decisionHour.buys} buy · ${decisionHour.sells} sell · ${decisionHour.holds} hold`
    : 'No decision data yet'

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <AgentPipeline
          agents={realAgents}
          marketTickCount={marketTickCount}
          lastMarketSymbol={lastMarketSymbol}
          marketLive={marketLive}
          decisionStats={decisionStats}
          proposalsCount={proposals.length}
        />

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KpiCard
            label="Agents Online"
            value={sanitizeValue(liveAgentCount)}
            lines={[`${realAgents.length} in pipeline · live = heartbeat < 2m`]}
          />
          <KpiCard
            label="Market Data"
            value={sanitizeValue(marketTickCount)}
            lines={[`${lastMarketSymbol ?? '—'} · ${marketLive ? 'streaming' : 'idle'}`]}
          />
          <KpiCard label="Decisions · 1h" value={sanitizeValue(decisionsLastHour)} lines={[decisionBreakdown]} />
          <KpiCard
            label="Notifications · 1h"
            value={sanitizeValue(recentNotificationCount)}
            lines={[`${notifications.length} stored (max 20)`, lastNotificationLabel(notifications)]}
          />
        </div>
      </section>

      <section className="space-y-2">
        <GroupLabel>Live Activity</GroupLabel>
        <ActivityTimeline items={activityItems} />
      </section>

      <section className="space-y-2">
        <GroupLabel>Reasoning</GroupLabel>
        <LiveReasoningPanel />
      </section>

      <section className="space-y-2">
        <GroupLabel>Intelligence</GroupLabel>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:items-start">
          <LLMHealthPanel />
          <ToolGovernancePanel />
          <PromptEvolutionPanel />
        </div>
      </section>

      <section className="space-y-2">
        <GroupLabel>Learning Loop</GroupLabel>
        <LearningLoopPanel />
      </section>

      <section className="space-y-2">
        <GroupLabel>Agents</GroupLabel>
        <AgentScorecards />
        <AgentStatusTable
          realAgents={realAgents}
          agentInstances={agentInstances}
          showNoAgentDataMessage={showNoAgentDataMessage}
        />
      </section>

      <section className="space-y-2">
        <GroupLabel>Activity</GroupLabel>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:items-start">
          <RecentDecisionsPanel stats={decisionStats} recent={recentDecisions} />
          <NotificationFeed notifications={notifications} wsConnected={wsConnected} />
        </div>
      </section>

      <section className="space-y-2">
        <GroupLabel>Diagnostics</GroupLabel>
        <SystemDiagnostics
          isInMemoryMode={isInMemoryMode}
          agentStatuses={agentStatuses}
          agentInstances={agentInstances}
          agentLogs={agentLogs}
          wiringFreshness={wiringFreshness}
          apiHealth={apiHealth}
        />
      </section>
    </div>
  )
}
