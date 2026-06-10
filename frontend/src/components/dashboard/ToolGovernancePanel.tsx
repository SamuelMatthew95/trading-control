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

const TOOL_COLUMNS = ['Tool', 'Status', 'Calls', 'Alpha', 'Latency', 'Err'] as const

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
        'flex items-start gap-2 rounded-lg border px-3 py-2',
        suggestion.severity === 'warning'
          ? 'border-amber-300 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/20'
          : 'border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-900/20',
      )}
    >
      <span
        className={cn(
          'shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold uppercase',
          actionBadgeClass(suggestion.action),
        )}
      >
        {suggestion.action}
      </span>
      <div className="min-w-0">
        <span className="font-mono text-xs text-slate-800 dark:text-slate-200">
          {suggestion.tool}
        </span>
        <p className="text-xs leading-snug text-slate-500 dark:text-slate-400">{suggestion.reason}</p>
      </div>
    </div>
  )
}

const TD = 'px-3 py-2 align-top'
const TD_NUM = 'px-3 py-2 text-right align-top font-mono text-xs tabular-nums whitespace-nowrap'

function ToolTableRow({ tool }: { tool: Tool }) {
  const exercised = tool.call_count > 0
  return (
    <tr className="border-t border-slate-100 dark:border-slate-800/70">
      {/* Tool name + gating / unlock / unused-reason sublines */}
      <td className={TD}>
        <span
          className={cn(
            'font-mono text-sm',
            tool.enabled
              ? 'text-slate-800 dark:text-slate-200'
              : 'text-slate-400 line-through dark:text-slate-600',
          )}
        >
          {tool.name}
        </span>
        {tool.required_state_flags.length > 0 && (
          <p className="mt-0.5 font-mono text-xs text-amber-600 dark:text-amber-400">
            requires: {tool.required_state_flags.join(', ')}
          </p>
        )}
        {tool.unlocks.length > 0 && (
          <p className="mt-0.5 truncate font-mono text-xs text-slate-400">
            → unlocks {tool.unlocks.join(', ')}
          </p>
        )}
        {!exercised && (
          <p className="mt-0.5 text-xs italic text-slate-400">{unusedReason(tool)}</p>
        )}
      </td>

      {/* Enabled / disabled */}
      <td className={TD}>
        <span className="inline-flex items-center gap-1.5 text-xs">
          <span
            className={cn(
              'h-2 w-2 shrink-0 rounded-full',
              tool.enabled ? 'bg-emerald-500' : 'bg-slate-400',
            )}
          />
          <span className="text-slate-600 dark:text-slate-400">
            {tool.enabled ? 'on' : 'off'}
          </span>
        </span>
      </td>

      {/* Calls ledger */}
      <td className={TD_NUM}>
        {exercised ? (
          <span className="text-slate-700 dark:text-slate-300">
            {tool.call_count}× · {tool.success_count} ok
          </span>
        ) : (
          <span className="italic text-slate-400 dark:text-slate-600">unused</span>
        )}
      </td>

      {/* Alpha attribution */}
      <td className={TD_NUM}>
        <span className={exercised ? sentimentTextClass(tool.alpha_score) : 'text-slate-400'}>
          {tool.alpha_score >= 0 ? '+' : ''}
          {tool.alpha_score.toFixed(2)}
        </span>
        {!exercised && <span className="ml-1 text-slate-400 dark:text-slate-600">prior</span>}
      </td>

      {/* Latency */}
      <td className={cn(TD_NUM, 'text-slate-500 dark:text-slate-400')}>
        {tool.latency_ms.toFixed(0)}ms
      </td>

      {/* Failure rate */}
      <td
        className={cn(TD_NUM, tool.failure_rate > 0.5 ? 'text-rose-500' : 'text-slate-400')}
      >
        {(tool.failure_rate * 100).toFixed(0)}%
      </td>
    </tr>
  )
}

function PhaseTable({ phase, tools }: { phase: string; tools: Tool[] }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {phase}
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/30">
              {TOOL_COLUMNS.map((head, i) => (
                <th
                  key={head}
                  className={cn(
                    'px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400',
                    i === 0 ? 'text-left' : 'text-right',
                  )}
                >
                  {head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <ToolTableRow key={tool.name} tool={tool} />
            ))}
          </tbody>
        </table>
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
      {/* One-line plain-language framing, then the column legend. */}
      <p className={cn(mutedClass, 'mb-1')}>
        The data look-ups the reasoning LLM may consult before a buy/sell call — each is graded by
        the realized PnL of the trades it influenced, and money-losing (negative-alpha) tools are
        proposed for automatic disable.
      </p>
      <p className={cn(mutedClass, 'mb-3')}>
        <span className="font-semibold">On</span> = the AI may use it ·{' '}
        <span className="font-semibold">Off</span> = switched off.{' '}
        <span className="font-mono">Alpha</span> = profit credited to the tool (a{' '}
        <span className="font-mono">prior</span> tag = an early estimate before any trade has
        scored it). <span className="font-mono">Calls</span> = how many times it&apos;s been used.{' '}
        {exercisedCount}/{tools.length} have run on a live trade so far.
      </p>

      {suggestions.length > 0 && (
        <div className="mb-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            What the system suggests
          </p>
          <p className="text-xs leading-snug text-slate-400">
            <span className="font-semibold text-rose-600 dark:text-rose-400">Disable</span> = losing
            money, switch it off ·{' '}
            <span className="font-semibold text-emerald-600 dark:text-emerald-400">Prioritize</span> =
            the best earner, keep it ·{' '}
            <span className="font-semibold">Review</span> = not used yet, just watching. Disable
            suggestions become a proposal on the{' '}
            <span className="font-semibold">Proposals</span> page; approve it there and the tool is
            switched off automatically.
          </p>
          {suggestions.map((s, i) => (
            <SuggestionRow key={`${s.tool}-${s.action}-${i}`} suggestion={s} />
          ))}
        </div>
      )}

      {tools.length === 0 ? (
        <p className="text-sm text-slate-500">No tools registered.</p>
      ) : exercisedCount === 0 ? (
        // No telemetry yet: a full table of zeroed counters/prior alphas reads
        // as broken. Collapse to one explanatory state + the registered names.
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-5 text-center dark:border-slate-800 dark:bg-slate-900/30">
          <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
            No tool calls yet
          </p>
          <p className="mx-auto mt-1 max-w-md text-xs leading-snug text-slate-500 dark:text-slate-400">
            {tools.length} tools are registered and waiting; every alpha is still a seeded prior.
            The full ledger appears once the reasoning LLM starts consulting tools and closed
            trades let the GradeAgent attribute realized PnL to them.
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-1.5">
            {tools.map((tool) => (
              <span
                key={tool.name}
                title={`${tool.phase} · ${tool.enabled ? 'enabled' : 'disabled'}`}
                className={cn(
                  'rounded-md border border-slate-200 bg-white px-2 py-0.5 font-mono text-[11px] dark:border-slate-700 dark:bg-slate-800/50',
                  tool.enabled
                    ? 'text-slate-600 dark:text-slate-300'
                    : 'text-slate-400 line-through dark:text-slate-600',
                )}
              >
                {tool.name}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {byPhase.map((group) => (
            <PhaseTable key={group.phase} phase={group.phase} tools={group.tools} />
          ))}
        </div>
      )}
    </div>
  )
}
