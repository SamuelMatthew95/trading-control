import type { AgentInstance, AgentLog, AgentStatus } from '@/stores/useCodexStore'
import type { ApiHealth } from '@/hooks/useRestPoll'
import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { apiHealthBadgeClass } from '@/lib/dashboard-helpers'
import { formatAgeFromMs } from '@/lib/formatters'
import type { WiringFreshness } from './shared'

function formatWiringAge(ageMs: number | null): string {
  const age = formatAgeFromMs(ageMs)
  return age === '--' ? 'No recent timestamp' : `last ${age} ago`
}

export interface SystemDiagnosticsProps {
  isInMemoryMode: boolean
  agentStatuses: AgentStatus[]
  agentInstances: AgentInstance[]
  agentLogs: AgentLog[]
  wiringFreshness: WiringFreshness
  apiHealth: ApiHealth
}

/** Data-wiring health — where the dashboard numbers come from. For debugging. */
export function SystemDiagnostics({
  isInMemoryMode,
  agentStatuses,
  agentInstances,
  agentLogs,
  wiringFreshness,
  apiHealth,
}: SystemDiagnosticsProps) {
  const apiRows = [
    { label: 'dashboard/state', value: apiHealth.dashboardState },
    { label: 'agent-instances', value: apiHealth.agentInstances },
    { label: 'history/events', value: apiHealth.eventHistory },
  ]
  return (
    <div className={cardClass}>
      <p className={sectionTitleClass}>System Diagnostics</p>
      <p className={cn(mutedClass, 'mb-2')}>
        Data-wiring health — where these numbers come from. For debugging.
      </p>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
            isInMemoryMode ? 'bg-amber-400/10 text-amber-500' : 'bg-emerald-500/10 text-emerald-500',
          )}
        >
          <span
            className={cn('inline-block h-2 w-2 rounded-full', isInMemoryMode ? 'bg-amber-400' : 'bg-emerald-500')}
          />
          {isInMemoryMode ? 'DB: In-Memory Fallback' : 'DB: Connected'}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <p className={mutedClass}>
          Heartbeats (in-memory/Redis):{' '}
          <span className="font-mono text-slate-700 dark:text-slate-200">{agentStatuses.length}</span>
          <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.heartbeatAgeMs)}</span>
        </p>
        <p className={mutedClass}>
          Lifecycle rows (DB):{' '}
          <span className="font-mono text-slate-700 dark:text-slate-200">{agentInstances.length}</span>
          <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.instanceAgeMs)}</span>
        </p>
        <p className={mutedClass}>
          Agent logs (DB/WS):{' '}
          <span className="font-mono text-slate-700 dark:text-slate-200">{agentLogs.length}</span>
          <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.logAgeMs)}</span>
        </p>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {apiRows.map((apiRow) => (
          <span
            key={apiRow.label}
            className={cn(
              'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
              apiHealthBadgeClass(apiRow.value),
            )}
          >
            {apiRow.label}: {apiRow.value}
          </span>
        ))}
      </div>
    </div>
  )
}
