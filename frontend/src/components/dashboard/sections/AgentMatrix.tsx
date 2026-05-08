'use client'

import { TerminalCard, SectionHeader, EmptyState, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { toneForAgentStatus } from '@/lib/state'
import { displayAgentName } from '@/lib/constants/agentStates'
import { formatTimeAgo } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type { AgentSummary } from '@/lib/types'

interface AgentMatrixProps {
  agents: AgentSummary[]
  wsConnected: boolean
  className?: string
}

export function AgentMatrix({ agents, wsConnected, className }: AgentMatrixProps) {
  return (
    <TerminalCard className={className}>
      <SectionHeader
        title="Agent Matrix"
        right={<span className={UI_TEXT.muted}>{agents.length}</span>}
      />
      {agents.length === 0 ? (
        <EmptyState message={wsConnected ? 'No active agents' : 'Connecting…'} />
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {agents.map((agent) => (
            <div
              key={agent.name}
              className="rounded-[6px] border border-slate-200 p-3 transition-transform duration-150 hover:scale-[1.01] dark:border-slate-800"
            >
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {displayAgentName(agent.name)}
                </p>
                <StateIndicator tone={toneForAgentStatus(agent.status)} label={agent.status} />
              </div>
              <div className="mt-2 flex items-center justify-between">
                <p className={cn(UI_TEXT.cell)}>
                  {agent.realtimeCount + agent.persistedCount} events
                </p>
                <p className={UI_TEXT.muted}>
                  {agent.lastSeen ? formatTimeAgo(agent.lastSeen) : 'Never'}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </TerminalCard>
  )
}
