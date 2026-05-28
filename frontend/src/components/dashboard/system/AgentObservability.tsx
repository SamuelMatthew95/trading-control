'use client'

import { Brain } from 'lucide-react'

import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'

import { EmptyState } from './EmptyState'
import type { AgentStatus } from '@/stores/useCodexStore'

export interface AgentObservabilityProps {
  agentStatuses: AgentStatus[]
}

const isActiveStatus = (status: string): boolean => status === 'ACTIVE' || status === 'active'

const headers = ['Agent', 'Status', 'Events', 'Last Action'] as const

export function AgentObservability({ agentStatuses }: AgentObservabilityProps) {
  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Agent Observability</p>
      {agentStatuses.length === 0 ? (
        <EmptyState message="No agent status yet" icon={Brain} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                {headers.map((head) => (
                  <th
                    key={head}
                    className={cn(
                      'px-2 py-2 font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400',
                      head === 'Events' ? 'text-right' : 'text-left',
                    )}
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {agentStatuses.map((agent) => {
                const active = isActiveStatus(agent.status)
                return (
                  <tr key={agent.name} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="px-2 py-2 font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">
                      {agent.name}
                    </td>
                    <td className="px-2 py-2">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className={cn(
                            'h-2 w-2 rounded-full',
                            active ? 'animate-pulse bg-emerald-500' : 'bg-slate-400',
                          )}
                        />
                        <span className="text-xs">{agent.status}</span>
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {agent.event_count.toLocaleString()}
                    </td>
                    <td className="px-2 py-2 text-xs font-mono text-slate-600 dark:text-slate-400">
                      {agent.last_event || '—'}
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
