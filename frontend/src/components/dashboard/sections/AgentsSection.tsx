'use client'

import { MetricTile } from '@/components/terminal'
import { LLMHealthPanel } from '@/components/dashboard/LLMHealthPanel'
import { NotificationFeed } from '@/components/dashboard/NotificationFeed'
import { AgentStatusTable } from './AgentStatusTable'
import { AgentInstancesPanel } from './AgentInstancesPanel'
import { SystemDiagnosticsPanel } from './SystemDiagnosticsPanel'
import { formatNumber, formatTimestamp } from '@/lib/format'
import type {
  AgentInstance,
  AgentLog,
  AgentStatus as StoreAgentStatus,
  Notification,
} from '@/stores/useCodexStore'
import type { AgentSummary, ApiHealthState, WiringFreshness } from '@/lib/types'

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
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
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
          hint={
            notifications[0]?.timestamp
              ? `Last: ${formatTimestamp(notifications[0].timestamp)}`
              : 'No activity yet'
          }
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
