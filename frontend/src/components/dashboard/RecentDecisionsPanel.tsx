'use client'

import { useState } from 'react'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { SIDE_BUY, SIDE_SELL } from '@/constants/trading'

import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { actionBadgeClass } from '@/lib/dashboard-helpers'
import { extractToolInvocations, summarizeToolOutputs } from '@/lib/decision-tools'
import { formatTimestamp } from '@/lib/formatters'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { TraceButton } from '@/components/dashboard/TraceButton'
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

export function RecentDecisionsPanel({
  stats,
  recent,
  onSelectTrace,
}: {
  stats: DecisionStats | null
  recent: Array<Record<string, unknown>>
  /** Drill-down: open the full trace for a decision. Optional — the trace
   *  button only renders when wired AND the decision carries a trace_id. */
  onSelectTrace?: (traceId: string) => void
}) {
  const actionable = recent.filter((d) => {
    const action = String(d.action ?? '').toLowerCase()
    return action === SIDE_BUY || action === SIDE_SELL
  })
  const fallbackCount = actionable.filter(isFallbackDecision).length
  // Which decision's reasoning chain (tool ledger) is expanded. One at a time.
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className={sectionTitleClass}>{UI_COPY.decisions.title}</p>
          {fallbackCount > 0 && (
            <span
              title={UI_COPY.decisions.ruleBasedHeaderTitle}
              className="rounded-full bg-warning/15 px-2 py-0.5 text-3xs font-semibold uppercase tracking-caps text-warning"
            >
              {fallbackCount}/{actionable.length} {UI_COPY.decisions.ruleBased}
            </span>
          )}
        </div>
        {stats && (
          <div className="flex items-center gap-2 font-mono text-xs tabular-nums text-muted-foreground">
            <span className="text-3xs uppercase tracking-caps text-muted-foreground/70">
              {UI_COPY.decisions.lastHour}
            </span>
            <span className="text-success">
              {UI_COPY.decisions.buys} {stats.last_hour.buys}
            </span>
            <span className="text-danger">
              {UI_COPY.decisions.sells} {stats.last_hour.sells}
            </span>
            <span>
              {UI_COPY.decisions.holds} {stats.last_hour.holds}
            </span>
            <span className="text-muted-foreground/50">·</span>
            <span title={UI_COPY.decisions.allTimeTitle} className="text-3xs uppercase tracking-caps text-muted-foreground/70">
              {UI_COPY.decisions.allTime}
            </span>
            <span title={UI_COPY.decisions.allTimeTitle}>
              {UI_COPY.decisions.total} {stats.total}
            </span>
          </div>
        )}
      </div>

      {actionable.length === 0 ? (
        <EmptyState message={UI_COPY.empty.decisions} />
      ) : (
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {actionable.slice(0, 10).map((d, index) => {
            const action = String(d.action ?? '').toLowerCase()
            const symbol = String(d.symbol ?? NO_DATA)
            const priceNum = Number(d.price)
            const priceTxt = Number.isFinite(priceNum)
              ? `$${priceNum.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
              : NO_DATA
            const confNum = Number(d.confidence)
            const confTxt = Number.isFinite(confNum) ? `${(confNum * 100).toFixed(0)}%` : NO_DATA
            const ts = formatTimestamp(d.timestamp ? String(d.timestamp) : null)
            const decisionId = `${String(d.id ?? d.trace_id ?? index)}-${index}`
            const traceId = d.trace_id ? String(d.trace_id) : null
            const tools = extractToolInvocations(d)
            const isOpen = openId === decisionId
            return (
              <div key={decisionId} className="rounded-lg border px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className={cn('rounded px-2 py-0.5 text-xs font-semibold uppercase', actionBadgeClass(action.toUpperCase()))}>
                      {action || UI_COPY.terminal.defaultAction}
                    </span>
                    <span className="font-mono text-sm font-semibold text-foreground">{symbol}</span>
                    {isFallbackDecision(d) && (
                      <span
                        title={UI_COPY.decisions.ruleBasedRowTitle}
                        className="rounded bg-warning/15 px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-caps text-warning"
                      >
                        {UI_COPY.decisions.ruleBased}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 font-mono text-xs tabular-nums text-foreground/70">
                    {tools.length > 0 && (
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => setOpenId(isOpen ? null : decisionId)}
                        aria-expanded={isOpen}
                        className="h-5 px-1.5 text-3xs font-semibold uppercase tracking-caps"
                      >
                        {tools.length} tool{tools.length === 1 ? '' : 's'} {isOpen ? '▾' : '▸'}
                      </Button>
                    )}
                    {traceId && onSelectTrace && <TraceButton onClick={() => onSelectTrace(traceId)} />}
                    <span>{priceTxt}</span>
                    <span className="text-muted-foreground/50">·</span>
                    <span>{confTxt}</span>
                    <span className="text-muted-foreground/50">·</span>
                    <span>{ts}</span>
                  </div>
                </div>

                {isOpen && tools.length > 0 && (
                  <div className="mt-2 space-y-1 rounded-md border bg-muted/40 p-2">
                    <p className="text-3xs font-semibold uppercase tracking-caps text-muted-foreground/70">
                      {UI_COPY.decisions.reasoningChain}
                    </p>
                    {tools.map((tool, toolIndex) => {
                      const outputs = summarizeToolOutputs(tool.outputs)
                      return (
                        <div
                          key={`${decisionId}-tool-${toolIndex}`}
                          className="flex items-center gap-2 font-mono text-2xs tabular-nums"
                        >
                          <span className={tool.success === false ? 'text-danger' : 'text-success'} aria-hidden>
                            {tool.success === false ? '✗' : '✓'}
                          </span>
                          <span className="text-foreground/80">{tool.name ?? UI_COPY.decisions.toolFallback}</span>
                          {typeof tool.latency_ms === 'number' && (
                            <span className="text-muted-foreground/70">{tool.latency_ms.toFixed(0)}ms</span>
                          )}
                          {outputs && <span className="text-muted-foreground">· {outputs}</span>}
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
