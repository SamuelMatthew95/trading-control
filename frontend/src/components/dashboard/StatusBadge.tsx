import { AgentState } from '@/types/dashboard'

type UiStatus = 'Live' | 'Stale' | 'Error' | 'Idle'

const statusStyles: Record<UiStatus, string> = {
  Live: 'border-emerald-300/35 bg-emerald-300/10 text-emerald-300',
  Stale: 'border-amber-300/35 bg-amber-300/10 text-amber-300',
  Error: 'border-rose-300/35 bg-rose-300/10 text-rose-300',
  Idle: 'border-slate-400/35 bg-transparent text-slate-400',
}

const statusMap: Record<AgentState, UiStatus> = {
  running: 'Live',
  idle: 'Idle',
  failed: 'Error',
}

export function StatusBadge({ status }: { status: AgentState }) {
  const label = statusMap[status]
  return (
    <span className={`inline-flex items-center gap-1 rounded-[6px] border px-2 py-1 text-xs font-medium ${statusStyles[label]}`}>
      {label !== 'Idle' ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {label}
    </span>
  )
}
