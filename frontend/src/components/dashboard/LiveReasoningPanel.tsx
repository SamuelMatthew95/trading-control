'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { sentimentTextClass } from '@/lib/design/sentiment'
import { cn } from '@/lib/utils'

// Mirrors api/services/dashboard/prompt_os.py response models.
interface ToolView {
  name: string
  phase: string
  enabled: boolean
  alpha_score: number
  latency_ms: number
  failure_rate: number
  call_count: number
}
interface LiveView {
  node: string
  strategy_version: number | null
  config: Record<string, unknown>
  active_tools: ToolView[]
  assembled_prompt: string
  constitution: string
  output_contract: string
}
interface ChallengerView {
  challenger_id: string
  fills: number
  max_fills: number
  running: boolean
  variant: string | null
  tool_overrides: string[] | null
  config_diff: Record<string, unknown>
  differs_by: string
}
interface ProposalView {
  id: string
  proposal_type: string
  description: string
  confidence: number | null
  status: string
  applied: boolean
}
interface LiveReasoningResponse {
  champion: LiveView
  challengers: ChallengerView[]
  proposals: ProposalView[]
  tool_count: number
  timestamp: string
}

type LlmStatus = 'live' | 'degraded' | 'down' | 'unknown'

function coerceLlmStatus(value: unknown): LlmStatus {
  return value === 'live' || value === 'degraded' || value === 'down' ? value : 'unknown'
}

// Header indicator per LLM status. When the provider is degraded/down the live
// strategy below is still the configured one, but decisions are rule-based
// fallbacks — so the dot must stop claiming a healthy green "live".
const LLM_INDICATOR: Record<LlmStatus, { label: string; text: string; dot: string; pulse: boolean }> = {
  live: { label: 'live', text: 'text-emerald-500', dot: 'bg-emerald-500', pulse: true },
  degraded: { label: 'LLM degraded', text: 'text-amber-500', dot: 'bg-amber-500', pulse: false },
  down: { label: 'LLM down · fallback', text: 'text-rose-500', dot: 'bg-rose-500', pulse: false },
  unknown: { label: 'awaiting LLM', text: 'text-slate-400', dot: 'bg-slate-400', pulse: false },
}

function ToolChip({ tool }: { tool: ToolView }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 dark:border-slate-700 dark:bg-slate-800/50"
      title={`${tool.phase} · α ${tool.alpha_score.toFixed(2)} · ${tool.latency_ms.toFixed(0)}ms · ${tool.call_count} calls`}
    >
      <span className="font-mono text-[11px] text-slate-700 dark:text-slate-200">{tool.name}</span>
      <span className={cn('font-mono text-[10px] tabular-nums', sentimentTextClass(tool.alpha_score))}>
        α{tool.alpha_score >= 0 ? '+' : ''}
        {tool.alpha_score.toFixed(2)}
      </span>
      {tool.call_count > 0 && (
        <span className="font-mono text-[10px] tabular-nums text-slate-400">
          ×{tool.call_count}
        </span>
      )}
    </span>
  )
}

function diffEntries(obj: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(obj).map(([k, v]) => [
    k,
    typeof v === 'object' ? JSON.stringify(v) : String(v),
  ])
}

function ChallengerCard({ ch }: { ch: ChallengerView }) {
  const pct = ch.max_fills > 0 ? Math.min(100, Math.round((ch.fills / ch.max_fills) * 100)) : 0
  const diffs = diffEntries(ch.config_diff)
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn('h-2 w-2 rounded-full', ch.running ? 'bg-emerald-500' : 'bg-slate-400')}
          />
          <span className="font-mono text-xs text-slate-800 dark:text-slate-200">
            challenger {ch.challenger_id}
          </span>
        </div>
        <span className="rounded bg-indigo-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-indigo-600 dark:text-indigo-400">
          differs by {ch.differs_by}
        </span>
      </div>

      <div className="mt-2">
        <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
          <span>shadow progress</span>
          <span className="font-mono tabular-nums">
            {ch.fills}/{ch.max_fills}
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
          <div className="h-full rounded-full bg-indigo-500" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {ch.variant && (
        <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-400">
          prompt variant: {ch.variant}
        </p>
      )}
      {ch.tool_overrides && ch.tool_overrides.length > 0 && (
        <p className="mt-2 font-mono text-[11px] text-slate-500 dark:text-slate-400">
          tools: {ch.tool_overrides.join(', ')}
        </p>
      )}
      {diffs.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {diffs.map(([k, v]) => (
            <span
              key={k}
              className="rounded bg-slate-500/10 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:text-slate-300"
            >
              {k}={v}
            </span>
          ))}
        </div>
      ) : (
        !ch.variant && (
          <p className="mt-2 text-[11px] text-slate-400">
            Same prompt + tools as the live strategy.
          </p>
        )
      )}
    </div>
  )
}

function ProposalRow({ p }: { p: ProposalView }) {
  const statusClass =
    p.status === 'approved'
      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
      : p.status === 'rejected'
        ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
        : 'bg-slate-500/15 text-slate-500'
  return (
    <div className="rounded-lg border border-slate-200 p-2.5 dark:border-slate-800">
      <div className="flex items-center justify-between gap-2">
        <span className="rounded bg-slate-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          {p.proposal_type.replace(/_/g, ' ')}
        </span>
        <div className="flex items-center gap-1.5">
          {p.applied && (
            <span className="rounded bg-indigo-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-600 dark:text-indigo-400">
              applied
            </span>
          )}
          <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold', statusClass)}>
            {p.status}
          </span>
        </div>
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-snug text-slate-700 dark:text-slate-300">
        {p.description || '—'}
      </p>
      {p.confidence != null && (
        <p className="mt-0.5 font-mono text-[10px] text-slate-400">
          confidence {(p.confidence * 100).toFixed(0)}%
        </p>
      )}
    </div>
  )
}

export function LiveReasoningPanel() {
  const [data, setData] = useState<LiveReasoningResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [llmStatus, setLlmStatus] = useState<LlmStatus>('unknown')
  const [showPrompt, setShowPrompt] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await apiFetch<LiveReasoningResponse>(API_ENDPOINTS.DASHBOARD_PROMPT_OS)
        if (!cancelled) {
          setData(res)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'fetch_failed')
      }
      // LLM health is best-effort: it drives the live/degraded indicator, but a
      // failure here must not blank the reasoning cockpit.
      try {
        const health = await apiFetch<{ status?: string }>(API_ENDPOINTS.LLM_HEALTH)
        if (!cancelled) setLlmStatus(coerceLlmStatus(health?.status))
      } catch {
        /* keep the previous status */
      }
    }
    load()
    const id = window.setInterval(load, LEARNING_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const live = data?.champion
  const challengers = data?.challengers ?? []
  const proposals = data?.proposals ?? []
  const versionLabel = live?.strategy_version != null ? `v${live.strategy_version}` : 'default'
  const indicator = LLM_INDICATOR[llmStatus]
  const llmDegraded = llmStatus === 'down' || llmStatus === 'degraded'

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>Live Reasoning</p>
        {error ? (
          <span className="font-mono text-xs text-rose-500">err: {error}</span>
        ) : (
          <span className={cn('flex items-center gap-1.5 font-mono text-xs', indicator.text)}>
            <span className="relative flex h-2 w-2">
              {indicator.pulse && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              )}
              <span className={cn('relative inline-flex h-2 w-2 rounded-full', indicator.dot)} />
            </span>
            {indicator.label}
          </span>
        )}
      </div>
      <p className={cn(mutedClass, 'mb-3')}>
        Exactly what the buy/sell AI is running now: the fixed rulebook + the tools it&apos;s
        allowed to use + the answer format. Challengers shadow it; proposals would change it.
      </p>

      {llmDegraded && (
        <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] leading-snug text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-400">
          LLM provider is {llmStatus === 'down' ? 'unavailable' : 'degraded'} right now — live
          decisions are <strong>rule-based fallbacks</strong>, not model reasoning. The prompt and
          tools below are still the configured strategy.
        </div>
      )}

      {/* ── Live strategy: the prompt + active tools ───────────────────────── */}
      <div className="rounded-lg border border-slate-200 bg-slate-50/40 p-3 dark:border-slate-800 dark:bg-slate-900/30">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
              live
            </span>
            <span className="font-mono text-xs text-slate-600 dark:text-slate-300">
              node={live?.node ?? 'reasoning'} · strategy={versionLabel}
            </span>
          </div>
          <button
            onClick={() => setShowPrompt((s) => !s)}
            className="rounded border border-slate-300 px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:border-slate-400 dark:border-slate-700 dark:text-slate-300"
          >
            {showPrompt ? 'Hide prompt' : 'View live prompt'}
          </button>
        </div>

        <p className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Tools the AI may use ({live?.active_tools.length ?? 0})
        </p>
        {live && live.active_tools.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {live.active_tools.map((t) => (
              <ToolChip key={t.name} tool={t} />
            ))}
          </div>
        ) : (
          <p className="mt-1 text-[11px] text-slate-400">No tools eligible for this node.</p>
        )}

        {showPrompt && live && (
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100 dark:bg-black/40">
            {live.assembled_prompt}
          </pre>
        )}
      </div>

      {/* ── Challengers being tested + proposed changes ────────────────────── */}
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Challengers being tested
          </p>
          {challengers.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-800">
              No challenger running — the live strategy is uncontested.
            </p>
          ) : (
            <div className="space-y-2">
              {challengers.map((ch) => (
                <ChallengerCard key={ch.challenger_id} ch={ch} />
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Proposed changes
          </p>
          {proposals.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-800">
              No proposals yet — they arrive from the ReflectionAgent.
            </p>
          ) : (
            <div className="space-y-2">
              {proposals.map((p) => (
                <ProposalRow key={p.id} p={p} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
