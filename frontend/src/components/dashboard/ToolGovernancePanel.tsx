'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'

// Mirrors api.services.tool_registry.ToolMetadata serialization.
interface Tool {
  name: string
  phase: string
  description: string
  enabled: boolean
  alpha_score: number
  latency_ms: number
  failure_rate: number
  call_count: number
  required_state_flags: string[]
  unlocks: string[]
}

interface ToolRegistryResponse {
  tools: Tool[]
  capability_graph: Record<string, string[]>
  count: number
}

// DAG phase order — perception → memory → risk → execution → optimization.
const PHASE_ORDER = ['perception', 'memory', 'risk', 'execution', 'optimization'] as const

function alphaClass(alpha: number): string {
  if (alpha > 0.001) return 'text-emerald-600 dark:text-emerald-400'
  if (alpha < -0.001) return 'text-rose-600 dark:text-rose-400'
  return 'text-slate-500 dark:text-slate-400'
}

function ToolRow({ tool }: { tool: Tool }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className={cn('h-2 w-2 shrink-0 rounded-full', tool.enabled ? 'bg-emerald-500' : 'bg-slate-400')}
          />
          <span
            className={cn(
              'truncate font-mono text-xs',
              tool.enabled
                ? 'text-slate-800 dark:text-slate-200'
                : 'text-slate-400 line-through dark:text-slate-600',
            )}
          >
            {tool.name}
          </span>
        </div>
        {tool.required_state_flags.length > 0 && (
          <p className="mt-0.5 text-[10px] font-mono text-amber-600 dark:text-amber-400">
            requires: {tool.required_state_flags.join(', ')}
          </p>
        )}
        {tool.unlocks.length > 0 && (
          <p className="mt-0.5 truncate text-[10px] font-mono text-slate-400">
            → unlocks {tool.unlocks.join(', ')}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3 font-mono text-[11px] tabular-nums">
        <span className={alphaClass(tool.alpha_score)} title="alpha attribution">
          α {tool.alpha_score >= 0 ? '+' : ''}
          {tool.alpha_score.toFixed(2)}
        </span>
        <span className="text-slate-500 dark:text-slate-400" title="avg latency">
          {tool.latency_ms.toFixed(0)}ms
        </span>
        <span
          className={cn(
            tool.failure_rate > 0.5 ? 'text-rose-500' : 'text-slate-400',
          )}
          title="failure rate"
        >
          {(tool.failure_rate * 100).toFixed(0)}% err
        </span>
      </div>
    </div>
  )
}

export function ToolGovernancePanel() {
  const [data, setData] = useState<ToolRegistryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await apiFetch<ToolRegistryResponse>(API_ENDPOINTS.DASHBOARD_TOOLS)
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

  const tools = data?.tools ?? []
  const enabledCount = tools.filter((t) => t.enabled).length
  const byPhase = PHASE_ORDER.map((phase) => ({
    phase,
    tools: tools.filter((t) => t.phase === phase),
  })).filter((group) => group.tools.length > 0)

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>Tool Governance · Runtime Registry</p>
        {error ? (
          <span className="font-mono text-xs text-rose-500">err: {error}</span>
        ) : (
          <span className="font-mono text-xs text-slate-400">
            {enabledCount}/{tools.length} enabled
          </span>
        )}
      </div>
      <p className={cn(mutedClass, 'mb-3')}>
        Tools exposed per DAG phase — the LLM only ever sees the eligible subset. α = realized
        alpha attribution.
      </p>

      {tools.length === 0 ? (
        <p className="text-xs text-slate-500">No tools registered.</p>
      ) : (
        <div className="space-y-3">
          {byPhase.map((group) => (
            <div key={group.phase}>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                {group.phase}
              </p>
              <div className="space-y-1.5">
                {group.tools.map((tool) => (
                  <ToolRow key={tool.name} tool={tool} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
