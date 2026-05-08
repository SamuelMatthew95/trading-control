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
import { cn } from '@/lib/utils'
import { TONE_CLASSES } from '@/lib/state'
import { formatTimestamp, formatUptime } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type { AgentInstance, AgentStatus as StoreAgentStatus } from '@/stores/useCodexStore'

const HEADERS = ['Instance Key', 'Pool', 'Status', 'Events', 'Uptime', 'Started'] as const

interface AgentInstancesPanelProps {
  instances: AgentInstance[]
  agentStatuses: StoreAgentStatus[]
}

export function AgentInstancesPanel({ instances, agentStatuses }: AgentInstancesPanelProps) {
  if (instances.length === 0) {
    const someActive = agentStatuses.some(
      (a) => String(a.status).toUpperCase() === 'ACTIVE',
    )
    return (
      <TerminalCard>
        <SectionHeader title="Agent Instances" />
        <div className="space-y-2">
          <EmptyState message="No instances registered yet" />
          {someActive ? (
            <p className={cn(UI_TEXT.muted, TONE_CLASSES.warn.text)}>
              Agents are reporting ACTIVE heartbeats, but no lifecycle records were returned.
              Check agent_instances DB writes.
            </p>
          ) : null}
        </div>
      </TerminalCard>
    )
  }
  return (
    <TerminalCard padded>
      <SectionHeader title="Agent Instances" />
      <div className="max-h-48 overflow-y-auto">
        <TerminalTable headers={HEADERS} rightAlignedColumns={[3]}>
          {instances.map((inst) => (
            <TerminalRow key={inst.id}>
              <TerminalCell numeric>{inst.instance_key}</TerminalCell>
              <TerminalCell className="text-xs text-slate-600 dark:text-slate-400">
                {inst.pool_name}
              </TerminalCell>
              <TerminalCell>
                <StateIndicator
                  tone={inst.status === 'active' ? 'pos' : 'muted'}
                  label={inst.status}
                />
              </TerminalCell>
              <TerminalCell numeric align="right">{inst.event_count}</TerminalCell>
              <TerminalCell numeric>{formatUptime(inst.uptime_seconds)}</TerminalCell>
              <TerminalCell numeric>{formatTimestamp(inst.started_at)}</TerminalCell>
            </TerminalRow>
          ))}
        </TerminalTable>
      </div>
    </TerminalCard>
  )
}
