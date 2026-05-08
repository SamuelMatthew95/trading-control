'use client'

import { TerminalCard, SectionHeader, EmptyState, StateIndicator } from '@/components/terminal'
import { toneForAgentStatus } from '@/lib/state'
import { displayAgentName } from '@/lib/constants/agentStates'
import { formatTimeAgo } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { ROW_BETWEEN } from '@/lib/styles'
import type { AgentSummary } from '@/lib/types'

interface AgentMatrixProps {
  agents: AgentSummary[]
  wsConnected: boolean
  className?: string
}

const AGENT_TILE_CLASS =
  'rounded-[6px] border border-slate-200 p-3 transition-transform duration-150 hover:scale-[1.01] dark:border-slate-800'

const AGENT_NAME_LABEL = 'text-sm font-semibold text-slate-900 dark:text-slate-100'
const AGENT_TILE_GRID = 'grid grid-cols-1 gap-2 sm:grid-cols-2'

function lastSeenLabel(lastSeen: Date | null): string {
  if (!lastSeen) return 'Never'
  return formatTimeAgo(lastSeen)
}

function totalEvents(agent: AgentSummary): number {
  return agent.realtimeCount + agent.persistedCount
}

function AgentMatrixTile(props: { agent: AgentSummary }) {
  const { agent } = props
  return (
    <div className={AGENT_TILE_CLASS}>
      <div className={ROW_BETWEEN}>
        <p className={AGENT_NAME_LABEL}>{displayAgentName(agent.name)}</p>
        <StateIndicator tone={toneForAgentStatus(agent.status)} label={agent.status} />
      </div>
      <div className={`mt-2 ${ROW_BETWEEN}`}>
        <p className={UI_TEXT.cell}>{totalEvents(agent)} events</p>
        <p className={UI_TEXT.muted}>{lastSeenLabel(agent.lastSeen)}</p>
      </div>
    </div>
  )
}

function emptyMessage(wsConnected: boolean): string {
  return wsConnected ? 'No active agents' : 'Connecting…'
}

export function AgentMatrix(props: AgentMatrixProps) {
  const { agents, wsConnected, className } = props
  return (
    <TerminalCard className={className}>
      <SectionHeader
        title="Agent Matrix"
        right={<span className={UI_TEXT.muted}>{agents.length}</span>}
      />
      {agents.length === 0 ? (
        <EmptyState message={emptyMessage(wsConnected)} />
      ) : (
        <div className={AGENT_TILE_GRID}>
          {agents.map((agent) => (
            <AgentMatrixTile key={agent.name} agent={agent} />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}
