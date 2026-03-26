'use client'

import { useEffect, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { Bot, Activity, Brain, CheckCircle, RefreshCw, Lightbulb, Clock, Bell } from 'lucide-react'
import { cn } from '@/lib/utils'

interface AgentStatus {
  id: string
  name: string
  icon: any
  status: 'active' | 'idle' | 'error'
  heartbeat: boolean
  lastSeen: string
  metrics: Record<string, string | number>
  tier: 'active' | 'challenger' | 'retired'
}

const AGENT_CONFIGS = [
  {
    id: 'signal_generator',
    name: 'SignalGenerator',
    icon: Activity,
    tier: 'active' as const,
    metrics: ['ticks_processed', 'signals_generated']
  },
  {
    id: 'reasoning_agent', 
    name: 'ReasoningAgent',
    icon: Brain,
    tier: 'active' as const,
    metrics: ['llm_provider', 'latency', 'current_decision']
  },
  {
    id: 'grade_agent',
    name: 'GradeAgent', 
    icon: CheckCircle,
    tier: 'active' as const,
    metrics: ['last_grade_run', 'actions_taken']
  },
  {
    id: 'ic_updater',
    name: 'ICUpdater',
    icon: RefreshCw,
    tier: 'challenger' as const,
    metrics: ['factor_weights_status']
  },
  {
    id: 'reflection_agent',
    name: 'ReflectionAgent',
    icon: Lightbulb,
    tier: 'active' as const,
    metrics: ['hypothesis_count', 'last_run']
  },
  {
    id: 'strategy_proposer',
    name: 'StrategyProposer',
    icon: Bot,
    tier: 'challenger' as const,
    metrics: ['pending_proposals']
  },
  {
    id: 'history_agent',
    name: 'HistoryAgent',
    icon: Clock,
    tier: 'retired' as const,
    metrics: ['pattern_status']
  },
  {
    id: 'notification_agent',
    name: 'NotificationAgent',
    icon: Bell,
    tier: 'active' as const,
    metrics: ['queue_health']
  }
]

export function AgentMonitor() {
  const { agentLogs, systemMetrics } = useCodexStore()
  const [agents, setAgents] = useState<AgentStatus[]>([])

  useEffect(() => {
    const agentStatuses: AgentStatus[] = AGENT_CONFIGS.map(config => {
      // Get recent logs for this agent
      const recentLogs = agentLogs.filter(log => 
        log.agent_name === config.name || 
        log.agent_name?.toLowerCase().includes(config.id.split('_')[0])
      ).slice(0, 10)

      const lastLog = recentLogs[0]
      const isHealthy = recentLogs.some(log => 
        log.event_type !== 'error' && 
        new Date(log.timestamp).getTime() > Date.now() - 60000 // Last minute
      )

      // Get metrics from system metrics
      const metrics: Record<string, string | number> = {}
      config.metrics.forEach(metric => {
        if (metric === 'latency') {
          const latencies = recentLogs.map(l => l.latency_ms || 0).filter(l => l > 0)
          metrics[metric] = latencies.length > 0 ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) + 'ms' : '--'
        } else if (metric === 'ticks_processed') {
          metrics[metric] = recentLogs.length || 0
        } else if (metric === 'signals_generated') {
          metrics[metric] = recentLogs.filter(l => l.event_type === 'signal').length || 0
        } else if (metric === 'actions_taken') {
          metrics[metric] = recentLogs.filter(l => l.action).length || 0
        } else if (metric === 'hypothesis_count') {
          metrics[metric] = recentLogs.filter(l => l.event_type === 'reflection').length || 0
        } else if (metric === 'pending_proposals') {
          metrics[metric] = Math.floor(Math.random() * 5) // Mock data
        } else if (metric === 'queue_health') {
          metrics[metric] = isHealthy ? 'Healthy' : 'Stale'
        } else {
          metrics[metric] = '--'
        }
      })

      return {
        id: config.id,
        name: config.name,
        icon: config.icon,
        status: isHealthy ? 'active' : lastLog ? 'idle' : 'error',
        heartbeat: isHealthy,
        lastSeen: lastLog?.timestamp || new Date().toISOString(),
        metrics,
        tier: config.tier
      }
    })

    setAgents(agentStatuses)
  }, [agentLogs, systemMetrics])

  const getTierColor = (tier: string) => {
    switch (tier) {
      case 'active': return 'border-green-500/20 bg-green-500/5'
      case 'challenger': return 'border-yellow-500/20 bg-yellow-500/5'
      case 'retired': return 'border-slate-500/20 bg-slate-500/5'
      default: return 'border-slate-200/20 bg-slate-200/5'
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-500'
      case 'idle': return 'bg-yellow-500'
      case 'error': return 'bg-red-500'
      default: return 'bg-slate-400'
    }
  }

  return (
    <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Live Agent Monitor
        </h3>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Real-time
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {agents.map((agent) => {
          const Icon = agent.icon
          return (
            <div
              key={agent.id}
              className={cn(
                "relative border rounded-lg p-4 transition-all duration-200 hover:shadow-md",
                getTierColor(agent.tier)
              )}
            >
              {/* Heartbeat LED */}
              <div className="absolute top-2 right-2">
                <div className={cn(
                  "w-2 h-2 rounded-full transition-all duration-300",
                  agent.heartbeat ? "bg-green-500 animate-pulse" : "bg-slate-400"
                )} />
              </div>

              {/* Agent Icon and Name */}
              <div className="flex items-center gap-3 mb-3">
                <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                  <Icon className="w-4 h-4 text-slate-600 dark:text-slate-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">
                    {agent.name}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 capitalize">
                    {agent.tier}
                  </p>
                </div>
              </div>

              {/* Metrics */}
              <div className="space-y-1">
                {Object.entries(agent.metrics).slice(0, 2).map(([key, value]) => (
                  <div key={key} className="flex justify-between items-center">
                    <span className="text-xs text-slate-600 dark:text-slate-400 truncate">
                      {key.replace(/_/g, ' ')}
                    </span>
                    <span className="text-xs font-mono text-slate-900 dark:text-slate-100">
                      {value}
                    </span>
                  </div>
                ))}
              </div>

              {/* Status Bar */}
              <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {agent.status}
                  </span>
                  <div className={cn(
                    "w-1.5 h-1.5 rounded-full",
                    getStatusColor(agent.status)
                  )} />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="mt-6 pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="flex items-center justify-center gap-6 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full" />
            <span className="text-slate-600 dark:text-slate-400">Active</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-yellow-500 rounded-full" />
            <span className="text-slate-600 dark:text-slate-400">Challenger</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-slate-500 rounded-full" />
            <span className="text-slate-600 dark:text-slate-400">Retired</span>
          </div>
        </div>
      </div>
    </div>
  )
}
