import { AgentState, AgentStatus } from '@/types/dashboard'

const statusStyles: Record<AgentStatus, string> = {
  Live: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:border-emerald-300/35 dark:bg-emerald-300/10 dark:text-emerald-300',
  Stale: 'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:border-amber-300/35 dark:bg-amber-300/10 dark:text-amber-300',
  Error: 'border-rose-500/35 bg-rose-500/10 text-rose-700 dark:border-rose-300/35 dark:bg-rose-300/10 dark:text-rose-300',
  Idle: 'border-slate-400/35 bg-transparent text-slate-500 dark:text-slate-400',
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
    <span className={`inline-flex items-center gap-1 rounded-[6px] border px-2 py-1 text-xs font-medium ${statusStyles[label]}`}>
      {label !== 'Idle' ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {label}
    </span>
  )
}
