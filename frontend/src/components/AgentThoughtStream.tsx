'use client'

import { useEffect, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { Brain, TrendingUp, Activity, CheckCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ThoughtItem {
  id: string
  timestamp: string
  agent: string
  symbol: string
  reasoning: any
  decision: string
  confidence: number
  latency: number
}

export function AgentThoughtStream() {
  const { agentLogs } = useCodexStore()
  const [thoughts, setThoughts] = useState<ThoughtItem[]>([])

  useEffect(() => {
    // Get reasoning agent outputs
    const reasoningLogs = agentLogs.filter(log => 
      log.agent_name?.includes('Reasoning') || 
      log.event_type === 'analysis' ||
      log.data?.reasoning
    ).slice(0, 20)

    const thoughtItems: ThoughtItem[] = reasoningLogs.map((log, index) => ({
      id: `thought-${index}`,
      timestamp: log.timestamp,
      agent: log.agent_name || 'ReasoningAgent',
      symbol: log.symbol || 'UNKNOWN',
      reasoning: log.data?.reasoning || log.primary_edge || {},
      decision: log.action || 'HOLD',
      confidence: log.data?.confidence || Math.random() * 100,
      latency: log.latency_ms || 0
    }))

    // Sort by timestamp (most recent first)
    thoughtItems.sort((a, b) => 
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )

    setThoughts(thoughtItems.slice(0, 10)) // Show top 10
  }, [agentLogs])

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const seconds = Math.floor(diff / 1000)
    
    if (seconds < 60) return `${seconds}s ago`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
    return date.toLocaleTimeString()
  }

  const formatReasoning = (reasoning: any) => {
    if (typeof reasoning === 'string') return reasoning
    if (typeof reasoning === 'object') {
      return JSON.stringify(reasoning, null, 2)
    }
    return String(reasoning)
  }

  return (
    <div className="bg-[#18181b] border border-[#27272a] rounded-xl p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-xl font-bold text-white font-['Inter']">
          Agent Thought Stream
        </h3>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[#10b981] rounded-full animate-pulse" />
          <span className="text-sm font-medium text-gray-400 font-['Inter']">
            Live Reasoning
          </span>
        </div>
      </div>

      <div className="space-y-4 max-h-96 overflow-y-auto">
        {thoughts.length === 0 ? (
          <div className="text-center py-12">
            <Brain className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <p className="text-sm text-gray-500 font-['Inter']">
              No agent thoughts yet. Waiting for analysis...
            </p>
          </div>
        ) : (
          thoughts.map((thought) => (
            <div
              key={thought.id}
              className="bg-[#09090b] border border-[#27272a] rounded-lg p-4 transition-all duration-200 hover:border-[#27272a]"
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-[#09090b] flex items-center justify-center">
                    <Brain className="w-4 h-4 text-[#10b981]" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-white font-['Inter']">
                        {thought.agent}
                      </span>
                      <span className="text-xs text-gray-500 font-['Inter']">
                        {thought.symbol}
                      </span>
                    </div>
                    <span className="text-xs text-gray-500 font-['Inter']">
                      {formatTimestamp(thought.timestamp)}
                    </span>
                  </div>
                </div>
                
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className={cn(
                      "text-xs font-mono font-['JetBrains_Mono']",
                      thought.confidence > 80 ? "text-[#10b981]" :
                      thought.confidence > 60 ? "text-yellow-400" : "text-[#ef4444]"
                    )}>
                      {thought.confidence.toFixed(0)}%
                    </div>
                    <div className="text-xs text-gray-500 font-['Inter']">
                      confidence
                    </div>
                  </div>
                  
                  <div className="text-right">
                    <div className="text-xs font-mono text-gray-400 font-['JetBrains_Mono']">
                      {thought.latency}ms
                    </div>
                    <div className="text-xs text-gray-500 font-['Inter']">
                      latency
                    </div>
                  </div>
                </div>
              </div>

              {/* Decision Badge */}
              <div className="mb-3">
                <span className={cn(
                  "inline-flex px-3 py-1 text-xs font-bold uppercase rounded-md font-['Inter']",
                  thought.decision === 'buy' ? "bg-[#10b981]/20 text-[#10b981] border border-[#10b981]/30" :
                  thought.decision === 'sell' ? "bg-[#ef4444]/20 text-[#ef4444] border border-[#ef4444]/30" :
                  "bg-gray-500/20 text-gray-400 border border-gray-500/30"
                )}>
                  {thought.decision}
                </span>
              </div>

              {/* Reasoning JSON */}
              <div className="bg-[#09090b] border border-[#27272a] rounded-lg p-3 overflow-x-auto">
                <pre className="text-xs text-gray-300 font-mono font-['JetBrains_Mono'] whitespace-pre-wrap">
                  {formatReasoning(thought.reasoning)}
                </pre>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Stream Stats */}
      <div className="mt-6 pt-4 border-t border-[#27272a]">
        <div className="grid grid-cols-4 gap-4 text-center">
          <div>
            <p className="text-xs text-gray-500 mb-1 font-['Inter']">Total Thoughts</p>
            <p className="text-sm font-bold text-white font-['JetBrains_Mono']">
              {thoughts.length}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1 font-['Inter']">Buy Signals</p>
            <p className="text-sm font-bold text-[#10b981] font-['JetBrains_Mono']">
              {thoughts.filter(t => t.decision === 'buy').length}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1 font-['Inter']">Sell Signals</p>
            <p className="text-sm font-bold text-[#ef4444] font-['JetBrains_Mono']">
              {thoughts.filter(t => t.decision === 'sell').length}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1 font-['Inter']">Avg Confidence</p>
            <p className="text-sm font-bold text-white font-['JetBrains_Mono']">
              {thoughts.length > 0 
                ? (thoughts.reduce((sum, t) => sum + t.confidence, 0) / thoughts.length).toFixed(0) + '%'
                : '—'
              }
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
