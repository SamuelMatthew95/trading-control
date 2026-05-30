import type { AgentSummary } from '@/lib/agent-pipeline'
import { cn } from '@/lib/utils'
import { formatTimeAgo } from '@/lib/formatters'
import { agentDisplayName } from '@/constants/agents'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { agentStatusDotClass } from '@/lib/dashboard-helpers'
import { EmptyState } from './shared'

const COLUMNS = ['Agent', 'Status', 'Source', 'Events', 'Last Seen']

function formatAgentSource(source: AgentSummary['source']): string {
  if (source === 'realtime') return 'Realtime'
  if (source === 'persisted') return 'Persisted'
  return 'Hybrid'
}

export interface AgentStatusTableProps {
  realAgents: AgentSummary[]
  showNoAgentDataMessage: boolean
}

/** Live heartbeat detail for every agent in the pipeline. */
export function AgentStatusTable({ realAgents, showNoAgentDataMessage }: AgentStatusTableProps) {
  return (
    <div className={cardClass}>
      <p className={sectionTitleClass}>Agent Status</p>
      <p className={cn(mutedClass, 'mb-3')}>
        Live heartbeat detail for every agent in the pipeline above.
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800">
              {COLUMNS.map((head) => (
                <th
                  key={head}
                  className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400"
                >
                  {head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showNoAgentDataMessage ? (
              <tr>
                <td colSpan={5} className="px-2 py-8">
                  <EmptyState message="No active agents" />
                </td>
              </tr>
            ) : (
              realAgents.map((agent) => (
                <tr key={agent.name} className="border-t border-slate-200 py-2 dark:border-slate-800">
                  <td className="px-2 py-2 text-sm font-sans text-slate-900 dark:text-slate-100">
                    {agentDisplayName(agent.name)}
                  </td>
                  <td className="px-2 py-2 text-xs font-sans">
                    <span className="inline-flex items-center gap-2">
                      <span className={cn('h-2 w-2 rounded-full', agentStatusDotClass(agent.status))} />
                      <span className="text-slate-700 dark:text-slate-300">{agent.status}</span>
                    </span>
                  </td>
                  <td className="px-2 py-2 text-xs font-sans text-slate-700 dark:text-slate-300">
                    {formatAgentSource(agent.source)}
                  </td>
                  <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                    {agent.realtimeCount + agent.persistedCount > 0 ? (
                      <>{(agent.realtimeCount + agent.persistedCount).toLocaleString()} events</>
                    ) : (
                      <span className="text-slate-400 dark:text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                    {agent.lastSeen ? formatTimeAgo(agent.lastSeen) : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
