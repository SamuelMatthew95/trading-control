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
import {
  SCROLL_LIST_INSTANCES,
  SECONDARY_TEXT,
  STACK_TIGHT,
} from '@/lib/styles'
import type { AgentInstance, AgentStatus as StoreAgentStatus } from '@/stores/useCodexStore'

const HEADERS = ['Instance Key', 'Pool', 'Status', 'Events', 'Uptime', 'Started'] as const

interface AgentInstancesPanelProps {
  instances: AgentInstance[]
  agentStatuses: StoreAgentStatus[]
}

function hasActiveAgent(statuses: StoreAgentStatus[]): boolean {
  return statuses.some((status) => String(status.status).toUpperCase() === 'ACTIVE')
}

function InstanceRow(props: { instance: AgentInstance }) {
  const { instance } = props
  return (
    <TerminalRow key={instance.id}>
      <TerminalCell numeric>{instance.instance_key}</TerminalCell>
      <TerminalCell className={cn('text-xs', SECONDARY_TEXT)}>{instance.pool_name}</TerminalCell>
      <TerminalCell>
        <StateIndicator
          tone={instance.status === 'active' ? 'pos' : 'muted'}
          label={instance.status}
        />
      </TerminalCell>
      <TerminalCell numeric align="right">
        {instance.event_count}
      </TerminalCell>
      <TerminalCell numeric>{formatUptime(instance.uptime_seconds)}</TerminalCell>
      <TerminalCell numeric>{formatTimestamp(instance.started_at)}</TerminalCell>
    </TerminalRow>
  )
}

function EmptyInstancesPanel(props: { agentStatuses: StoreAgentStatus[] }) {
  return (
    <TerminalCard>
      <SectionHeader title="Agent Instances" />
      <div className={STACK_TIGHT}>
        <EmptyState message="No instances registered yet" />
        {hasActiveAgent(props.agentStatuses) ? (
          <p className={cn(UI_TEXT.muted, TONE_CLASSES.warn.text)}>
            Agents are reporting ACTIVE heartbeats, but no lifecycle records were returned.
            Check agent_instances DB writes.
          </p>
        ) : null}
      </div>
    </TerminalCard>
  )
}

export function AgentInstancesPanel(props: AgentInstancesPanelProps) {
  const { instances, agentStatuses } = props
  if (instances.length === 0) {
    return <EmptyInstancesPanel agentStatuses={agentStatuses} />
  }
  return (
    <TerminalCard padded>
      <SectionHeader title="Agent Instances" />
      <div className={SCROLL_LIST_INSTANCES}>
        <TerminalTable headers={HEADERS} rightAlignedColumns={[3]}>
          {instances.map((instance) => (
            <InstanceRow key={instance.id} instance={instance} />
          ))}
        </TerminalTable>
      </div>
    </TerminalCard>
  )
}
