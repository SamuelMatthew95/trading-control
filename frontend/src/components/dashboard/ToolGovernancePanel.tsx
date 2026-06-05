'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { sentimentTextClass } from '@/lib/design/sentiment'
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
  success_count: number
  required_state_flags: string[]
  unlocks: string[]
}

// Mirrors api.services.tool_registry.ToolSuggestion serialization.
interface Suggestion {
  tool: string
  action: string
  severity: string
  reason: string
}

interface ToolRegistryResponse {
  tools: Tool[]
  capability_graph: Record<string, string[]>
  suggestions: Suggestion[]
  count: number
}

// DAG phase order — perception → memory → risk → execution → optimization.
const PHASE_ORDER = ['perception', 'memory', 'risk', 'execution', 'optimization'] as const

// The reasoning LLM only ever gathers perception + memory tools. Risk/execution/
// optimization tools live on downstream nodes, so they read as "unused" here by
// design — not because they are broken.
const REASONING_PHASES = new Set(['perception', 'memory'])

// Plain-English WHY a tool has never been called, so "unused" is never a mystery.
function unusedReason(tool: Tool): string {
  if (!REASONING_PHASES.has(tool.phase)) {
    return 'downstream tool — runs on a live order/risk event, not at reasoning time'
  }
  if (tool.required_state_flags.length > 0) {
    return `gated — eligible only once ${tool.required_state_flags.join(', ')} is set`
  }
  return 'eligible — the reasoning LLM has not selected it yet'
}

function actionBadgeClass(action: string): string {
  if (action === 'disable') return 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
  if (action === 'prioritize') return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
  return 'bg-slate-500/15 text-slate-500 dark:text-slate-400'
}

function SuggestionRow({ suggestion }: { suggestion: Suggestion }) {
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-lg border px-3 py-1.5',
        suggestion.severity === 'warning'
          ? 'border-amber-300 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/20'
          : 'border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-900/20',
      )}
    >
      <span
        className={cn(
          'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase',
          actionBadgeClass(suggestion.action),
        )}
      >
        {suggestion.action}
      </span>
      <div className="min-w-0">
        <span className="font-mono text-xs text-slate-800 dark:text-slate-200">
          {suggestion.tool}
        </span>
        <p className="text-[11px] leading-snug text-slate-500 dark:text-slate-400">
          {suggestion.reason}
        </p>
      </div>
    </div>
  )
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
        {tool.call_count === 0 && (
          <p className="mt-0.5 text-[10px] italic text-slate-400" title="why this tool is unused">
            {unusedReason(tool)}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3 font-mono text-[11px] tabular-nums">
        {tool.call_count > 0 ? (
          <span
            className="text-slate-500 dark:text-slate-400"
            title="decision-time calls (successful)"
          >
            {tool.call_count}× · {tool.success_count} ok
          </span>
        ) : (
          <span className="italic text-slate-400 dark:text-slate-600" title="never exercised">
            unused
          </span>
        )}
        <span
          className={cn(tool.call_count > 0 ? sentimentTextClass(tool.alpha_score) : 'text-slate-400')}
          title={
            tool.call_count > 0
              ? 'realized-PnL alpha attribution'
              : 'seeded prior — no live trades have informed this tool yet'
          }
        >
          α {tool.alpha_score >= 0 ? '+' : ''}
          {tool.alpha_score.toFixed(2)}
          {tool.call_count === 0 && <span className="ml-0.5 not-italic">prior</span>}
        </span>
        <span className="text-slate-500 dark:text-slate-400" title="avg latency">
          {tool.latency_ms.toFixed(0)}ms
        </span>
        <span
          className={cn(tool.failure_rate > 0.5 ? 'text-rose-500' : 'text-slate-400')}
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
  const suggestions = data?.suggestions ?? []
  const enabledCount = tools.filter((t) => t.enabled).length
  const exercisedCount = tools.filter((t) => t.call_count > 0).length
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
        Tools exposed per DAG phase — the reasoning LLM only ever sees the eligible subset for the
        current phase/state. A <span className="text-emerald-500">green dot</span> = currently
        enabled; a <span className="line-through">struck-through</span> grey name = disabled.{' '}
        <span className="font-mono">N×</span> = times the LLM called the tool;{' '}
        <span className="font-mono">α</span> = realized-PnL attribution once closed trades inform it
        (a <span className="font-mono">prior</span> tag means the score is a seed, not yet earned).{' '}
        {exercisedCount}/{tools.length} exercised live.
      </p>

      {suggestions.length > 0 && (
        <div className="mb-3 space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Governance Recommendations
          </p>
          <p className="text-[10px] leading-snug text-slate-400">
            Suggested actions — <span className="font-semibold">nothing here is applied
            automatically</span>; a human (or an approved TOOL_GOVERNANCE proposal) acts on them.
            These are recommendations, not each tool&apos;s current state shown below.
          </p>
          {suggestions.map((s, i) => (
            <SuggestionRow key={`${s.tool}-${s.action}-${i}`} suggestion={s} />
          ))}
        </div>
      )}

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
