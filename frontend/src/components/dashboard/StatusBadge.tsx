import type { AgentState } from '@/types/dashboard'
import { StatusChip } from '@/components/terminal'
import { toneForAgentStatus, type AgentStatus } from '@/lib/state'

const STATUS_MAP: Record<AgentState, AgentStatus> = {
  running: 'Live',
  idle: 'Idle',
  failed: 'Error',
}

export function StatusBadge({ status }: { status: AgentState }) {
  const label = STATUS_MAP[status]
  return <StatusChip label={label} tone={toneForAgentStatus(label)} dot={label !== 'Idle'} />
}
