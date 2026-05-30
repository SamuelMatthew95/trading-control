import type { AgentInstance, AgentStatus } from '@/stores/useCodexStore'
import { cn } from '@/lib/utils'
import { formatTimestamp } from '@/lib/formatters'
import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { EmptyState } from './shared'

const COLUMNS = ['Instance Key', 'Pool', 'Status', 'Events', 'Uptime', 'Started']

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

export interface AgentInstancesTableProps {
  agentInstances: AgentInstance[]
  agentStatuses: AgentStatus[]
}

/** Per-instance lifecycle rows (DB-backed) with an active-without-records hint. */
export function AgentInstancesTable({ agentInstances, agentStatuses }: AgentInstancesTableProps) {
  const hasActiveHeartbeat = agentStatuses.some(
    (agent) => String(agent.status).toUpperCase() === 'ACTIVE',
  )
  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Agent Instances</p>
      {agentInstances.length === 0 ? (
        <div className="space-y-2">
          <EmptyState message="No instances registered yet" />
          {hasActiveHeartbeat && (
            <p className="text-xs font-sans text-amber-600 dark:text-amber-400">
              Agents are reporting ACTIVE heartbeats, but no lifecycle records were returned. Check
              agent_instances DB writes.
            </p>
          )}
        </div>
      ) : (
        <div className="max-h-48 overflow-y-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                {COLUMNS.map((head) => (
                  <th
                    key={head}
                    className="px-2 py-1.5 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {agentInstances.map((inst) => {
                const isActive = inst.status === 'active'
                return (
                  <tr key={inst.id} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="px-2 py-1.5 text-xs font-mono text-slate-900 dark:text-slate-100">
                      {inst.instance_key}
                    </td>
                    <td className="px-2 py-1.5 text-xs font-sans text-slate-600 dark:text-slate-400">
                      {inst.pool_name}
                    </td>
                    <td className="px-2 py-1.5 text-xs font-sans">
                      <span className="inline-flex items-center gap-1.5">
                        <span className={cn('h-2 w-2 rounded-full', isActive ? 'bg-emerald-500' : 'bg-slate-400')} />
                        <span className={isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500'}>
                          {inst.status}
                        </span>
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right text-xs font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {inst.event_count}
                    </td>
                    <td className="px-2 py-1.5 text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {formatUptime(inst.uptime_seconds)}
                    </td>
                    <td className="px-2 py-1.5 text-xs font-mono text-slate-500">
                      {formatTimestamp(inst.started_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
