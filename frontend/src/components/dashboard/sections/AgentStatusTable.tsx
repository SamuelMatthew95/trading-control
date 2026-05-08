'use client'

import {
  TerminalCard,
  SectionHeader,
  EmptyState,
  TerminalTable,
  TerminalRow,
  TerminalCell,
  StateIndicator,
} from '@/components/terminal'
import { toneForAgentStatus } from '@/lib/state'
import { displayAgentName } from '@/lib/constants/agentStates'
import { formatTimeAgo } from '@/lib/format'
import type { AgentSummary } from '@/lib/types'

const HEADERS = ['Agent', 'Status', 'Source', 'Events', 'Last Seen'] as const

const SOURCE_LABEL: Record<AgentSummary['source'], string> = {
  realtime: 'Realtime',
  persisted: 'Persisted',
  hybrid: 'Hybrid',
}

interface AgentStatusTableProps {
  agents: AgentSummary[]
  showEmpty: boolean
}

/**
 * Collapse the noise case of `rt:0 · db:0` (an agent that has registered
 * a heartbeat but never produced an event) to a single em-dash so the
 * table reads "no events" at a glance instead of "two zeros".
 */
function eventCountText(agent: AgentSummary): string {
  if (agent.realtimeCount === 0 && agent.persistedCount === 0) return '—'
  return `rt:${agent.realtimeCount} · db:${agent.persistedCount}`
}

function lastSeenText(agent: AgentSummary): string {
  return agent.lastSeen ? formatTimeAgo(agent.lastSeen) : '—'
}

function AgentStatusRow(props: { agent: AgentSummary }) {
  const { agent } = props
  return (
    <TerminalRow key={agent.name}>
      <TerminalCell>{displayAgentName(agent.name)}</TerminalCell>
      <TerminalCell>
        <StateIndicator tone={toneForAgentStatus(agent.status)} label={agent.status} />
      </TerminalCell>
      <TerminalCell className="text-xs">{SOURCE_LABEL[agent.source]}</TerminalCell>
      <TerminalCell numeric align="right">
        {eventCountText(agent)}
      </TerminalCell>
      <TerminalCell numeric>{lastSeenText(agent)}</TerminalCell>
    </TerminalRow>
  )
}

function EmptyAgentsRow() {
  return (
    <TerminalRow>
      <TerminalCell colSpan={HEADERS.length} padded>
        <EmptyState message="No active agents" />
      </TerminalCell>
    </TerminalRow>
  )
}

export function AgentStatusTable(props: AgentStatusTableProps) {
  const { agents, showEmpty } = props
  return (
    <TerminalCard padded>
      <SectionHeader title="Agent Status" />
      <TerminalTable headers={HEADERS} rightAlignedColumns={[3]}>
        {showEmpty ? (
          <EmptyAgentsRow />
        ) : (
          agents.map((agent) => <AgentStatusRow key={agent.name} agent={agent} />)
        )}
      </TerminalTable>
    </TerminalCard>
  )
}
