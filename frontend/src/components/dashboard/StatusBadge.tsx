import { AgentState, AgentStatus } from '@/types/dashboard'
import { TONE_BADGE, type Tone } from '@/lib/design/sentiment'

const STATUS_TONE: Record<AgentStatus, Tone> = {
  Live: 'success',
  Stale: 'warning',
  Error: 'danger',
  Idle: 'neutral',
}

function toUiStatus(status: string): AgentStatus {
  switch (status.toLowerCase()) {
    case 'running': case 'active': case 'live': return 'Live'
    case 'stale': case 'waiting': return 'Stale'
    case 'failed': case 'error': case 'offline': return 'Error'
    default: return 'Idle'
  }
}

export function StatusBadge({ status }: { status: AgentState | string }) {
  const label = toUiStatus(String(status ?? ''))
  return (
    <span className={`inline-flex items-center gap-1 rounded-[6px] border px-2 py-1 text-xs font-medium ${TONE_BADGE[STATUS_TONE[label]]}`}>
      {label !== 'Idle' ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {label}
    </span>
  )
}
