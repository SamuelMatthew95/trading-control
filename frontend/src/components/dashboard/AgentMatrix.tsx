'use client'

import { cn } from '@/lib/utils'
import { useAgents } from '@/hooks/useRealtimeData'

const TRACKED_AGENTS = [
  'SIGNAL_AGENT',
  'REASONING_AGENT',
  'GRADE_AGENT',
  'IC_UPDATER',
  'REFLECTION_AGENT',
  'STRATEGY_PROPOSER',
  'NOTIFICATION_AGENT',
] as const

function AgentCardSkeleton() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-2 h-4 w-24 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mb-1 h-5 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="h-3 w-32 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
    </div>
  )
}

function StatusBadge({ status }: { status: 'ACTIVE' | 'WAITING' | 'STALE' | 'ERROR' | 'OFFLINE' }) {
  const getStatusConfig = () => {
    switch (status) {
      case 'ACTIVE':
        return {
          bgColor: 'bg-green-100 dark:bg-green-900/30',
          textColor: 'text-green-700 dark:text-green-400',
          dotColor: 'bg-green-500'
        }
      case 'WAITING':
        return {
          bgColor: 'bg-slate-100 dark:bg-slate-900/30',
          textColor: 'text-slate-700 dark:text-slate-400',
          dotColor: 'bg-slate-500'
        }
      case 'STALE':
        return {
          bgColor: 'bg-amber-100 dark:bg-amber-900/30',
          textColor: 'text-amber-700 dark:text-amber-400',
          dotColor: 'bg-amber-500'
        }
      case 'ERROR':
        return {
          bgColor: 'bg-red-100 dark:bg-red-900/30',
          textColor: 'text-red-700 dark:text-red-400',
          dotColor: 'bg-red-500'
        }
      case 'OFFLINE':
        return {
          bgColor: 'bg-red-100 dark:bg-red-900/30',
          textColor: 'text-red-700 dark:text-red-400 line-through',
          dotColor: 'bg-red-500'
        }
    }
  }

  const config = getStatusConfig()

  return (
    <div className={cn(
      'inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium',
      config.bgColor,
      config.textColor
    )}>
      <div className={cn('h-1.5 w-1.5 rounded-full', config.dotColor)} />
      {status}
    </div>
  )
}

function formatTimeAgo(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength - 3) + '...'
}

export function AgentMatrix() {
  const { agents, isLoading, error } = useAgents()

  if (error) {
    return (
      <div className="space-y-4">
        <h3 className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">
          Agent Matrix
        </h3>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950/50">
          <div className="flex items-center gap-2">
            <div className="text-red-500">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">Agent Status Error</p>
              <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const agentList = TRACKED_AGENTS.map(name => ({
    name,
    status: agents[name]?.status || 'OFFLINE',
    lastEvent: agents[name]?.last_event || 'No data available',
    eventCount: agents[name]?.event_count || 0,
    secondsAgo: agents[name]?.seconds_ago || 999999
  }))

  const allAgentsWaiting = agentList.every(agent => 
    agent.status === 'WAITING' && agent.eventCount === 0
  )

  return (
    <div className="space-y-4">
      <h3 className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">
        Agent Matrix
      </h3>

      {allAgentsWaiting && !isLoading && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/50">
          <div className="flex items-center gap-2">
            <div className="text-amber-500">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-amber-800 dark:text-amber-200">Agents Waiting</p>
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Agents are waiting for market events. Ensure the price poller worker is running on Render.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {isLoading && Object.keys(agents).length === 0 ? (
          Array.from({ length: 7 }).map((_, index) => (
            <AgentCardSkeleton key={index} />
          ))
        ) : (
          agentList.map((agent) => (
            <div 
              key={agent.name}
              className="rounded-lg border border-slate-200 bg-white p-3 transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold font-mono text-slate-900 dark:text-slate-100">
                  {agent.name}
                </span>
                <StatusBadge status={agent.status} />
              </div>
              
              <div className="mb-1">
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  {truncateText(agent.lastEvent, 60)}
                </p>
              </div>
              
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500 dark:text-slate-400">
                  {agent.eventCount} events
                </span>
                <span className="text-slate-500 dark:text-slate-400">
                  {agent.secondsAgo < 999999 ? formatTimeAgo(agent.secondsAgo) : 'never'}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
