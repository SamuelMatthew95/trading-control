'use client'

import { useState } from 'react'

import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { extractToolInvocations, summarizeToolOutputs } from '@/lib/decision-tools'
import { formatTimestamp } from '@/lib/formatters'
import { EmptyState } from '@/components/ui/empty-state'
import type { DecisionStats } from '@/hooks/useRestPoll'

// A decision is a rule-based fallback (not real model reasoning) when the agent
// couldn't run the LLM: it sets llm_succeeded=false and prefixes its reasoning
// summary with "fallback:". Surfacing this stops a confident-looking buy/sell
// row from being mistaken for a model-reasoned call when the LLM is down.
function isFallbackDecision(d: Record<string, unknown>): boolean {
  if (d.llm_succeeded === false) return true
  const summary = typeof d.reasoning_summary === 'string' ? d.reasoning_summary : ''
  return summary.startsWith('fallback:')
}

function EmptyDecisions() {
  return <EmptyState message="No buy/sell decisions yet" />
}

export function RecentDecisionsPanel({
  stats,
  recent,
}: {
  stats: DecisionStats | null
  recent: Array<Record<string, unknown>>
}) {
  const actionable = recent.filter((d) => {
    const action = String(d.action ?? '').toLowerCase()
    return action === 'buy' || action === 'sell'
  })
  const fallbackCount = actionable.filter(isFallbackDecision).length
  // Which decision's reasoning chain (tool ledger) is expanded. One at a time.
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className={sectionTitleClass}>Recent Decisions</p>
          {fallbackCount > 0 && (
            <span
              title="LLM unavailable — these are rule-based fallback decisions, not model reasoning."
              className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400"
            >
              {fallbackCount}/{actionable.length} rule-based
            </span>
          )}
        </div>
        {stats && (
          <div className="flex items-center gap-2 font-mono text-xs tabular-nums text-slate-500 dark:text-slate-400">
            <span className="text-[10px] uppercase tracking-wide text-slate-400 dark:text-slate-600">
              last 1h
            </span>
            <span className="text-emerald-600 dark:text-emerald-400">
              Buys: {stats.last_hour.buys}
            </span>
            <span className="text-rose-600 dark:text-rose-400">
              Sells: {stats.last_hour.sells}
            </span>
            <span>Holds: {stats.last_hour.holds}</span>
            <span className="text-slate-300 dark:text-slate-700">·</span>
            <span
              title="All decisions stored (most-recent, capped at 50) — not a last-hour figure, so it won't equal Buys + Sells + Holds"
              className="text-[10px] uppercase tracking-wide text-slate-400 dark:text-slate-600"
            >
              all-time
            </span>
            <span title="All decisions stored (most-recent, capped at 50) — not a last-hour figure, so it won't equal Buys + Sells + Holds">
              Total: {stats.total}
            </span>
          </div>
        )}
      </div>

      {actionable.length === 0 ? (
        <EmptyDecisions />
      ) : (
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {actionable.slice(0, 10).map((d, index) => {
            const action = String(d.action ?? '').toLowerCase()
            const symbol = String(d.symbol ?? '--')
            const priceNum = Number(d.price)
            const priceTxt = Number.isFinite(priceNum)
              ? `$${priceNum.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
              : '--'
            const confNum = Number(d.confidence)
            const confTxt = Number.isFinite(confNum) ? `${(confNum * 100).toFixed(0)}%` : '--'
            const ts = formatTimestamp(d.timestamp ? String(d.timestamp) : null)
            const badgeClass =
              action === 'buy'
                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
            const decisionId = `${String(d.id ?? d.trace_id ?? index)}-${index}`
            const tools = extractToolInvocations(d)
            const isOpen = openId === decisionId
            return (
              <div
                key={decisionId}
                className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className={cn('rounded px-2 py-0.5 text-xs font-semibold uppercase', badgeClass)}>
                      {action || 'hold'}
                    </span>
                    <span className="font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {symbol}
                    </span>
                    {isFallbackDecision(d) && (
                      <span
                        title="LLM unavailable — rule-based fallback, not model reasoning."
                        className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400"
                      >
                        rule-based
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 font-mono text-xs tabular-nums text-slate-600 dark:text-slate-300">
                    {tools.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setOpenId(isOpen ? null : decisionId)}
                        aria-expanded={isOpen}
                        className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 transition-colors hover:border-slate-400 hover:text-slate-700 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                      >
                        {tools.length} tool{tools.length === 1 ? '' : 's'} {isOpen ? '▾' : '▸'}
                      </button>
                    )}
                    <span>{priceTxt}</span>
                    <span className="text-slate-400">·</span>
                    <span>{confTxt}</span>
                    <span className="text-slate-400">·</span>
                    <span>{ts}</span>
                  </div>
                </div>

                {isOpen && tools.length > 0 && (
                  <div className="mt-2 space-y-1 rounded-md border border-slate-200 bg-slate-50/60 p-2 dark:border-slate-800 dark:bg-slate-900/40">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                      Reasoning chain · tools this decision used
                    </p>
                    {tools.map((tool, toolIndex) => {
                      const outputs = summarizeToolOutputs(tool.outputs)
                      return (
                        <div
                          key={`${decisionId}-tool-${toolIndex}`}
                          className="flex items-center gap-2 font-mono text-[11px] tabular-nums"
                        >
                          <span
                            className={tool.success === false ? 'text-rose-500' : 'text-emerald-500'}
                            aria-hidden
                          >
                            {tool.success === false ? '✗' : '✓'}
                          </span>
                          <span className="text-slate-700 dark:text-slate-200">{tool.name ?? 'tool'}</span>
                          {typeof tool.latency_ms === 'number' && (
                            <span className="text-slate-400">{tool.latency_ms.toFixed(0)}ms</span>
                          )}
                          {outputs && <span className="text-slate-500 dark:text-slate-400">· {outputs}</span>}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
