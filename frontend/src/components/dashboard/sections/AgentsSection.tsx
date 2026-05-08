'use client'

import { MetricTile } from '@/components/terminal'
import { LLMHealthPanel } from '@/components/dashboard/LLMHealthPanel'
import { NotificationFeed } from '@/components/dashboard/NotificationFeed'
import { METRIC_ROW_GRID, STACK } from '@/lib/styles'
import { AgentStatusTable } from './AgentStatusTable'
import { AgentInstancesPanel } from './AgentInstancesPanel'
import { SystemDiagnosticsPanel } from './SystemDiagnosticsPanel'
import { formatNumber, formatTimestamp, parseTimestamp } from '@/lib/format'
import type {
  AgentInstance,
  AgentLog,
  AgentStatus as StoreAgentStatus,
  Notification,
} from '@/stores/useCodexStore'
import type { AgentSummary, ApiHealthState, WiringFreshness } from '@/lib/types'

function notificationActivityHint(timestamp: string | null | undefined): string {
  // Use parseTimestamp first so an invalid value (e.g. "not-a-date") falls
  // through to "No activity yet" rather than rendering "Last: —".
  const parsed = parseTimestamp(timestamp)
  if (!parsed) return 'No activity yet'
  return `Last: ${formatTimestamp(parsed)}`
}

interface AgentsSectionProps {
  marketTickCount: number
  lastMarketSymbol: string | null
  agents: AgentSummary[]
  agentLogs: AgentLog[]
  notifications: Notification[]
  isInMemoryMode: boolean
  agentStatuses: StoreAgentStatus[]
  agentInstances: AgentInstance[]
  wiringFreshness: WiringFreshness
  apiHealth: {
    dashboardState: ApiHealthState
    agentInstances: ApiHealthState
    eventHistory: ApiHealthState
  }
  showNoAgentDataMessage: boolean
  wsConnected: boolean
}

export function AgentsSection({
  marketTickCount,
  lastMarketSymbol,
  agents,
  agentLogs,
  notifications,
  isInMemoryMode,
  agentStatuses,
  agentInstances,
  wiringFreshness,
  apiHealth,
  showNoAgentDataMessage,
  wsConnected,
}: AgentsSectionProps) {
  const liveAgentCount = agents.filter((a) => a.status === 'Live').length

  return (
    <div className={STACK}>
      <div className={METRIC_ROW_GRID}>
        <MetricTile
          label="Market Ticks"
          value={formatNumber(marketTickCount)}
          hint={`Last symbol: ${lastMarketSymbol ?? '—'}`}
        />
        <MetricTile
          label="Active Agents"
          value={formatNumber(liveAgentCount)}
          hint="Live heartbeat < 5s"
        />
        <MetricTile
          label="Pipeline Events"
          value={formatNumber(agentLogs.length)}
          hint="Processed events (runtime)"
        />
        <MetricTile
          label="Notifications"
          value={formatNumber(notifications.length)}
          hint={notificationActivityHint(notifications[0]?.timestamp)}
        />
      </div>

      <LLMHealthPanel />

      <SystemDiagnosticsPanel
        isInMemoryMode={isInMemoryMode}
        agentStatusesCount={agentStatuses.length}
        agentInstancesCount={agentInstances.length}
        agentLogsCount={agentLogs.length}
        wiringFreshness={wiringFreshness}
        apiHealth={apiHealth}
      />

      <AgentStatusTable agents={agents} showEmpty={showNoAgentDataMessage} />

      <AgentInstancesPanel instances={agentInstances} agentStatuses={agentStatuses} />

      <NotificationFeed notifications={notifications} wsConnected={wsConnected} />
    </div>
  )
}
