'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'

// Mirrors api.services.prompt_store.PromptStore directive records.
interface Directive {
  node: string
  text: string
  version: number
  rationale?: string
  source?: string
  updated_at?: string
}

// Mirrors api.services.dashboard.prompt_evolution.get_prompt_evolution_payload.
interface PromptEvolutionResponse {
  node: string
  active: Directive | null
  history: Directive[]
  version: number
  enabled: boolean
  auto_apply: boolean
}

function VersionTag({ version }: { version: number }) {
  return (
    <span className="shrink-0 rounded bg-indigo-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-indigo-600 dark:text-indigo-400">
      v{version}
    </span>
  )
}

export function PromptEvolutionPanel() {
  const [data, setData] = useState<PromptEvolutionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await apiFetch<PromptEvolutionResponse>(
          API_ENDPOINTS.DASHBOARD_PROMPT_EVOLUTION,
        )
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

  const active = data?.active ?? null
  const history = data?.history ?? []

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>Self-Evolving Prompt · Reasoning Directive</p>
        {error ? (
          <span className="font-mono text-xs text-rose-500">err: {error}</span>
        ) : (
          <span className="flex items-center gap-2 font-mono text-xs text-slate-400">
            <span
              className={cn(
                'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase',
                data?.enabled
                  ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                  : 'bg-slate-500/15 text-slate-500',
              )}
            >
              {data?.enabled ? 'evolving' : 'frozen'}
            </span>
            {data?.auto_apply ? 'auto-apply' : 'manual'}
          </span>
        )}
      </div>
      <p className={cn(mutedClass, 'mb-3')}>
        The learned directive the LLM refines each cycle — assembled beneath the immutable
        constitution. Reflection drafts it, an approved proposal promotes it, the next decision
        uses it.
      </p>

      {!active ? (
        <div className="space-y-2 text-xs text-slate-500 dark:text-slate-400">
          <p>
            No evolved directive yet — the reasoning agent runs on the{' '}
            <span className="font-medium text-slate-600 dark:text-slate-300">immutable constitution</span>{' '}
            alone. A directive is the learned guidance layered <em>beneath</em> it, and only
            appears after the learning loop closes a full cycle:
          </p>
          <ol className="space-y-1">
            <li className="flex gap-2">
              <span className="font-mono text-slate-400">1</span>
              <span>closed trades are graded</span>
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-slate-400">2</span>
              <span>Reflection drafts an improved directive</span>
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-slate-400">3</span>
              <span>
                it ships as a <span className="font-medium">PROMPT_EVOLUTION</span> proposal —
                review it on the Proposals page
              </span>
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-slate-400">4</span>
              <span>
                on {data?.auto_apply ? 'auto-apply' : 'approval'} it becomes the active directive,
                shown here with its version &amp; full history
              </span>
            </li>
          </ol>
          <p className="italic">
            {data?.enabled
              ? 'Evolution is on — nothing proposed yet (the loop is still warming up).'
              : 'Evolution is frozen — enable PROMPT_EVOLUTION to let the directive learn.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="rounded-lg border border-indigo-200 bg-indigo-50/40 px-3 py-2 dark:border-indigo-900/50 dark:bg-indigo-950/20">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                Active
              </span>
              <VersionTag version={active.version} />
            </div>
            <p className="whitespace-pre-wrap text-xs leading-snug text-slate-800 dark:text-slate-200">
              {active.text}
            </p>
            {active.rationale && (
              <p className="mt-1.5 text-[11px] italic text-slate-500 dark:text-slate-400">
                why: {active.rationale}
              </p>
            )}
          </div>

          {history.length > 0 && (
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                History
              </p>
              <div className="space-y-1.5">
                {history.map((d) => (
                  <div
                    key={d.version}
                    className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-1.5 dark:border-slate-800"
                  >
                    <VersionTag version={d.version} />
                    <p className="min-w-0 flex-1 truncate text-[11px] text-slate-500 dark:text-slate-400">
                      {d.text}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
