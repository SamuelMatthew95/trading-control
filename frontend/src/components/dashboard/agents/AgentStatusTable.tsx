import type { AgentInstance } from '@/stores/useCodexStore'
import type { AgentSummary } from '@/lib/agent-pipeline'
import { cn } from '@/lib/utils'
import { formatTimeAgo } from '@/lib/formatters'
import { agentDisplayName, canonicalAgentKey } from '@/constants/agents'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { EmptyState } from './shared'

// Numeric columns are right-aligned in BOTH the header and the cells so the
// table scans cleanly — a left header over right-aligned numbers reads ragged.
const COLUMNS: ReadonlyArray<{ label: string; align: 'left' | 'right' }> = [
  { label: 'Agent', align: 'left' },
  { label: 'Status', align: 'left' },
  { label: 'Source', align: 'left' },
  { label: 'Events', align: 'right' },
  { label: 'Uptime', align: 'right' },
  { label: 'Last Seen', align: 'right' },
]

function formatAgentSource(source: AgentSummary['source']): string {
  if (source === 'realtime') return 'Realtime'
  if (source === 'persisted') return 'Persisted'
  return 'Hybrid'
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

/**
 * Longest uptime (seconds) among the active instances of each agent pool, keyed
 * by canonical agent name. Folds the former Agent Instances table into this
 * single per-agent source of truth so the page no longer shows two overlapping
 * agent tables.
 */
function uptimeByAgent(agentInstances: AgentInstance[]): Map<string, number> {
  const byKey = new Map<string, number>()
  for (const inst of agentInstances) {
    if (inst.status !== 'active') continue
    const key = canonicalAgentKey(inst.pool_name)
    const seconds = inst.uptime_seconds ?? 0
    if (seconds > (byKey.get(key) ?? 0)) byKey.set(key, seconds)
  }
  return byKey
}

export interface AgentStatusTableProps {
  realAgents: AgentSummary[]
  agentInstances: AgentInstance[]
  showNoAgentDataMessage: boolean
  /** Drill-down: open the agent detail modal for this agent. Optional so the
   *  table still renders (non-interactive) where no handler is wired. */
  onSelect?: (name: string) => void
}

/** One row per agent: status, produced events, uptime, last heartbeat. */
export function AgentStatusTable({
  realAgents,
  agentInstances,
  showNoAgentDataMessage,
  onSelect,
}: AgentStatusTableProps) {
  const uptimes = uptimeByAgent(agentInstances)
  return (
    <div className={cardClass}>
      <p className={sectionTitleClass}>Agent Status</p>
      <p className={cn(mutedClass, 'mb-3')}>
        One row per agent — status, what it has produced, uptime, and last heartbeat.
        {onSelect ? ' Click a row to drill into its grade, dimensions, and recent activity.' : ''}
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800">
              {COLUMNS.map(({ label, align }) => (
                <th
                  key={label}
                  className={cn(
                    'px-2 py-2 text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400',
                    align === 'right' ? 'text-right' : 'text-left',
                  )}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showNoAgentDataMessage ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-2 py-8">
                  <EmptyState message="No active agents" />
                </td>
              </tr>
            ) : (
              realAgents.map((agent) => {
                const uptime = uptimes.get(canonicalAgentKey(agent.name))
                const clickable = Boolean(onSelect)
                return (
                  <tr
                    key={agent.name}
                    className={cn(
                      'border-t border-slate-200 py-2 dark:border-slate-800',
                      clickable &&
                        'cursor-pointer hover:bg-slate-50 focus:bg-slate-50 focus:outline-none dark:hover:bg-slate-800/40 dark:focus:bg-slate-800/40',
                    )}
                    onClick={clickable ? () => onSelect?.(agent.name) : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    role={clickable ? 'button' : undefined}
                    aria-label={clickable ? `View ${agentDisplayName(agent.name)} details` : undefined}
                    onKeyDown={
                      clickable
                        ? (e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              onSelect?.(agent.name)
                            }
                          }
                        : undefined
                    }
                  >
                    <td className="px-2 py-2 text-sm font-sans text-slate-900 dark:text-slate-100">
                      {agentDisplayName(agent.name)}
                    </td>
                    <td className="px-2 py-2 text-xs font-sans">
                      <StatusBadge status={agent.status} />
                    </td>
                    <td className="px-2 py-2 text-xs font-sans text-slate-700 dark:text-slate-300">
                      {formatAgentSource(agent.source)}
                    </td>
                    <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {agent.eventCount > 0 ? (
                        <>{agent.eventCount.toLocaleString()} events</>
                      ) : (
                        <span className="text-slate-400 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                      {uptime != null ? (
                        formatUptime(uptime)
                      ) : (
                        <span className="text-slate-400 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {agent.lastSeen ? formatTimeAgo(agent.lastSeen) : '—'}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
