'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS, gradeBg, tierBadge, tierLabel } from '@/lib/grade-colors'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'
import type { AgentPerformanceResponse, AgentScore } from '@/lib/agent-performance'
import { AgentDetailModal } from './AgentDetailModal'

function ScoreCard({ agent, onSelect }: { agent: AgentScore; onSelect: (name: string) => void }) {
  const exercised = agent.dimensions.filter((d) => d.data_available).length
  return (
    <button
      type="button"
      onClick={() => onSelect(agent.name)}
      className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 text-left transition-colors hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-slate-700 dark:hover:bg-slate-900/40"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-sans text-slate-900 dark:text-slate-100">
          {agent.display_name}
        </span>
        <span className={cn('shrink-0 rounded-md border px-1.5 py-0.5 text-xs font-bold', gradeBg(agent.grade))}>
          {agent.grade ?? '—'}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            'rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
            tierBadge(agent.tier),
          )}
        >
          {agent.promoted && <span className="mr-0.5">★</span>}
          {tierLabel(agent.tier)}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400">
          {agent.score_pct == null ? 'unrated' : `${agent.score_pct}%`}
        </span>
      </div>
      <p className={cn(mutedClass, 'text-[10px]')}>
        {agent.event_count.toLocaleString()} events · {exercised}/{agent.dimensions.length} dims scored
      </p>
    </button>
  )
}

export function AgentScorecards() {
  const [data, setData] = useState<AgentPerformanceResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await apiFetch<AgentPerformanceResponse>(API_ENDPOINTS.AGENTS_PERFORMANCE)
        if (!cancelled) {
          setData(res)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'fetch_failed')
      }
    }
    load()
    const id = window.setInterval(load, LEARNING_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const agents = data?.agents ?? []
  const promoted = data?.promoted ?? 0

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>Agent Scorecards</p>
        {error ? (
          <span className="font-mono text-xs text-rose-500">err: {error}</span>
        ) : (
          <span className="font-mono text-xs text-slate-400">{promoted} promoted</span>
        )}
      </div>
      <p className={cn(mutedClass, 'mb-3')}>
        Each agent graded on its own telemetry — liveness, run success, throughput, and latency.
        Click a card to see what it did, its grade breakdown, and its learnings. Sustained{' '}
        <span className="font-semibold">A</span> work earns a <span className="font-semibold">★ Promoted</span> tier.
      </p>

      {agents.length === 0 ? (
        <p className="text-xs text-slate-500">No agent telemetry yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
          {agents.map((agent) => (
            <ScoreCard key={agent.name} agent={agent} onSelect={setSelected} />
          ))}
        </div>
      )}

      {selected && <AgentDetailModal name={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
