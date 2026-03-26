'use client'

import { useEffect, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { Brain, TrendingUp, Clock, Activity, CheckCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ActivityItem {
  id: string
  type: 'reasoning' | 'trade' | 'signal' | 'position'
  timestamp: string
  agent: string
  content: string
  metadata?: Record<string, any>
}

export function ActivityFeed() {
  const { agentLogs, orders, positions } = useCodexStore()
  const [activities, setActivities] = useState<ActivityItem[]>([])

  useEffect(() => {
    const activityItems: ActivityItem[] = []

    // Add reasoning agent activities
    agentLogs
      .filter(log => log.agent_name?.includes('Reasoning') || log.event_type === 'analysis')
      .slice(0, 10)
      .forEach((log, index) => {
        activityItems.push({
          id: `reasoning-${index}`,
          type: 'reasoning',
          timestamp: log.timestamp,
          agent: log.agent_name || 'ReasoningAgent',
          content: log.primary_edge || log.data?.reasoning || 'Processing market analysis...',
          metadata: {
            symbol: log.symbol,
            latency: log.latency_ms,
            decision: log.action
          }
        })
      })

    // Add trade activities
    orders
      .filter(order => order.side === 'long' || order.side === 'short')
      .slice(0, 5)
      .forEach((order, index) => {
        activityItems.push({
          id: `trade-${index}`,
          type: 'trade',
          timestamp: order.timestamp || new Date().toISOString(),
          agent: 'TradeExecutor',
          content: `${order.side.toUpperCase()} position opened for ${order.symbol}`,
          metadata: {
            symbol: order.symbol,
            side: order.side,
            pnl: order.pnl,
            quantity: order.quantity
          }
        })
      })

    // Add signal activities
    agentLogs
      .filter(log => log.event_type === 'signal')
      .slice(0, 5)
      .forEach((log, index) => {
        activityItems.push({
          id: `signal-${index}`,
          type: 'signal',
          timestamp: log.timestamp,
          agent: 'SignalGenerator',
          content: `Signal generated: ${log.action?.toUpperCase() || 'HOLD'} for ${log.symbol}`,
          metadata: {
            symbol: log.symbol,
            action: log.action,
            confidence: log.data?.confidence
          }
        })
      })

    // Sort by timestamp (most recent first)
    activityItems.sort((a, b) => 
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )

    setActivities(activityItems.slice(0, 15)) // Limit to 15 most recent
  }, [agentLogs, orders, positions])

  const getActivityIcon = (type: string) => {
    switch (type) {
      case 'reasoning': return Brain
      case 'trade': return TrendingUp
      case 'signal': return Activity
      case 'position': return CheckCircle
      default: return Clock
    }
  }

  const getActivityColor = (type: string) => {
    switch (type) {
      case 'reasoning': return 'border-blue-500/20 bg-blue-500/5'
      case 'trade': return 'border-green-500/20 bg-green-500/5'
      case 'signal': return 'border-yellow-500/20 bg-yellow-500/5'
      case 'position': return 'border-purple-500/20 bg-purple-500/5'
      default: return 'border-slate-200/20 bg-slate-200/5'
    }
  }

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const minutes = Math.floor(diff / 60000)
    
    if (minutes < 1) return 'Just now'
    if (minutes < 60) return `${minutes}m ago`
    if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`
    return date.toLocaleDateString()
  }

  return (
    <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Agent Activity Feed
        </h3>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Live
          </span>
        </div>
      </div>

      <div className="space-y-3 max-h-96 overflow-y-auto">
        {activities.length === 0 ? (
          <div className="text-center py-12">
            <Activity className="h-12 w-12 text-slate-400 mx-auto mb-4" />
            <p className="text-sm text-slate-600 dark:text-slate-400">
              No agent activity yet. Waiting for signals...
            </p>
          </div>
        ) : (
          activities.map((activity) => {
            const Icon = getActivityIcon(activity.type)
            return (
              <div
                key={activity.id}
                className={cn(
                  "relative border rounded-lg p-4 transition-all duration-200 hover:shadow-md",
                  getActivityColor(activity.type)
                )}
              >
                <div className="flex items-start gap-3">
                  {/* Icon */}
                  <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Icon className="w-4 h-4 text-slate-600 dark:text-slate-400" />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-slate-900 dark:text-slate-100 capitalize">
                          {activity.type}
                        </span>
                        <span className="text-xs text-slate-500 dark:text-slate-400">
                          {activity.agent}
                        </span>
                      </div>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {formatTimestamp(activity.timestamp)}
                      </span>
                    </div>

                    <p className="text-sm text-slate-700 dark:text-slate-300 mb-2">
                      {activity.content}
                    </p>

                    {/* Metadata */}
                    {activity.metadata && (
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(activity.metadata).map(([key, value]) => (
                          <span
                            key={key}
                            className="inline-flex px-2 py-1 text-xs font-mono bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded"
                          >
                            {key}: {value}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Activity Summary */}
      <div className="mt-6 pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="grid grid-cols-4 gap-4 text-center">
          <div>
            <p className="text-xs text-slate-600 dark:text-slate-400 mb-1">Reasoning</p>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {activities.filter(a => a.type === 'reasoning').length}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-600 dark:text-slate-400 mb-1">Trades</p>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {activities.filter(a => a.type === 'trade').length}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-600 dark:text-slate-400 mb-1">Signals</p>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {activities.filter(a => a.type === 'signal').length}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-600 dark:text-slate-400 mb-1">Total</p>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {activities.length}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
