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
 * Plain-English event count.
 *
 * `realtimeCount` (heartbeats / WebSocket) and `persistedCount` (agent_instances
 * table) are two views of the same event stream, so the truthful "how many
 * events has this agent processed" number is the larger of the two. The old
 * `rt:X · db:Y` jargon was confusing and double-counted active agents like
 * Signal Agent (`rt:24624 · db:24612`) where the two columns are nearly equal.
 */
function eventCountText(agent: AgentSummary): string {
  const total = Math.max(agent.realtimeCount, agent.persistedCount)
  if (total === 0) return 'no events'
  if (total === 1) return '1 event'
  return `${total.toLocaleString('en-US')} events`
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
