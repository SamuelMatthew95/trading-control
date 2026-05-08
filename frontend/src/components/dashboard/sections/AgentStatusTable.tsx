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

export function AgentStatusTable({ agents, showEmpty }: AgentStatusTableProps) {
  return (
    <TerminalCard padded>
      <SectionHeader title="Agent Status" />
      <TerminalTable headers={HEADERS} rightAlignedColumns={[3]}>
        {showEmpty ? (
          <TerminalRow>
            <TerminalCell colSpan={HEADERS.length} padded>
              <EmptyState message="No active agents" />
            </TerminalCell>
          </TerminalRow>
        ) : (
          agents.map((agent) => (
            <TerminalRow key={agent.name}>
              <TerminalCell>{displayAgentName(agent.name)}</TerminalCell>
              <TerminalCell>
                <StateIndicator
                  tone={toneForAgentStatus(agent.status)}
                  label={agent.status}
                />
              </TerminalCell>
              <TerminalCell className="text-xs">{SOURCE_LABEL[agent.source]}</TerminalCell>
              <TerminalCell numeric align="right">
                rt:{agent.realtimeCount} · db:{agent.persistedCount}
              </TerminalCell>
              <TerminalCell numeric>
                {agent.lastSeen ? formatTimeAgo(agent.lastSeen) : '—'}
              </TerminalCell>
            </TerminalRow>
          ))
        )}
      </TerminalTable>
    </TerminalCard>
  )
}
