'use client'

import { useState } from 'react'

import type {
  AgentInstance,
  AgentLog,
  AgentHeartbeat,
  Notification,
  Proposal,
  RecentEvent,
  StreamStat,
} from '@/stores/useDashboardStore'
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
import { StatTile } from '@/components/ui/stat-tile'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { TraceModal } from '@/components/dashboard/TraceModal'
import { AgentScorecards } from './AgentScorecards'
import { SystemDiagnostics } from './SystemDiagnostics'
import { GroupLabel, type WiringFreshness } from './shared'

// Re-exported for backward compatibility (components/dashboard/agents/index.ts).
export type { WiringFreshness }

// ── Timing windows ──────────────────────────────────────────────────────────
const MARKET_LIVE_WINDOW_MS = 60_000
const NOTIFICATION_RECENT_WINDOW_MS = 3_600_000 // 1 hour

export interface AgentsDashboardProps {
  realAgents: AgentSummary[]
  wiringFreshness: WiringFreshness
  agentStatuses: AgentHeartbeat[]
  agentInstances: AgentInstance[]
  agentLogs: AgentLog[]
  notifications: Notification[]
  proposals: Proposal[]
  decisionStats: DecisionStats | null
  recentDecisions: Array<Record<string, unknown>>
  recentEvents: RecentEvent[]
  /** Closed round-trips this session — gates the learning stages' "waiting for
   *  closed trades" hint in the pipeline. */
  closedTradesCount: number
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
    closedTradesCount,
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

  // Drill-down: which trace's modal is open — shared by decisions + notifications.
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)

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
    : UI_COPY.agentsPage.noDecisionData

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
          closedTradesCount={closedTradesCount}
        />

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile
            label={UI_COPY.agentsPage.kpiAgentsOnline}
            value={sanitizeValue(liveAgentCount)}
            lines={[`${realAgents.length} ${UI_COPY.agentsPage.kpiAgentsOnlineNote}`]}
          />
          <StatTile
            label={UI_COPY.agentsPage.kpiMarketData}
            value={sanitizeValue(marketTickCount)}
            lines={[`${lastMarketSymbol ?? NO_DATA} · ${marketLive ? UI_COPY.agentsPage.streaming : UI_COPY.agentsPage.idle}`]}
          />
          <StatTile label={UI_COPY.agentsPage.kpiDecisionsHour} value={sanitizeValue(decisionsLastHour)} lines={[decisionBreakdown]} />
          <StatTile
            label={UI_COPY.agentsPage.kpiNotificationsHour}
            value={sanitizeValue(recentNotificationCount)}
            lines={[`${notifications.length} ${UI_COPY.agentsPage.storedNote}`, lastNotificationLabel(notifications)]}
          />
        </div>
      </section>

      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupLiveActivity}</GroupLabel>
        <ActivityTimeline items={activityItems} />
      </section>

      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupReasoning}</GroupLabel>
        <LiveReasoningPanel />
      </section>

      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupIntelligence}</GroupLabel>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:items-start">
          <LLMHealthPanel />
          <ToolGovernancePanel />
          <div className="xl:col-span-2">
            <PromptEvolutionPanel />
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupLearningLoop}</GroupLabel>
        <LearningLoopPanel />
      </section>

      {/* The scorecards are the single per-agent view: grade, tier, drill-in.
          The former Agent Status table duplicated them with status/source/uptime
          noise ("Live · Hybrid") that answered no operator question. */}
      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupAgents}</GroupLabel>
        <AgentScorecards />
      </section>

      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupActivity}</GroupLabel>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:items-start">
          <RecentDecisionsPanel
            stats={decisionStats}
            recent={recentDecisions}
            onSelectTrace={setActiveTraceId}
          />
          <NotificationFeed
            notifications={notifications}
            wsConnected={wsConnected}
            onSelectTrace={setActiveTraceId}
          />
        </div>
      </section>

      <section className="space-y-2">
        <GroupLabel>{UI_COPY.agentsPage.groupDiagnostics}</GroupLabel>
        <SystemDiagnostics
          isInMemoryMode={isInMemoryMode}
          agentStatuses={agentStatuses}
          agentInstances={agentInstances}
          agentLogs={agentLogs}
          wiringFreshness={wiringFreshness}
          apiHealth={apiHealth}
        />
      </section>

      {activeTraceId && (
        <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />
      )}
    </div>
  )
}
