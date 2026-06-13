'use client'

import { useState } from 'react'

import { cn } from '@/lib/utils'
import { NO_DATA } from '@/constants/copy'
import { formatTimeAgo, formatUSD, getField, toFiniteNum } from '@/lib/formatters'
import { actionTone, FIELD_REALIZED_PNL_PCT, isFallbackDecision, signed } from '@/lib/cognitive'
import type { TradeTrace } from '@/types/cognitive'

import { card, chip, CMD, COPY, FallbackTag, Grade, Step, ToolChain } from './cognitive-ui'

export function TracesPanel({ traces }: { traces: TradeTrace[] }) {
  const [open, setOpen] = useState<string | null>(traces[0]?.trace_id ?? null)
  if (traces.length === 0) {
    return <div className={cn(card, 'text-sm text-muted-foreground')}>{COPY.noTraces}</div>
  }
  return (
    <div className="space-y-2">
      {traces.map((trace) => {
        const isOpen = open === trace.trace_id
        const decision = trace.decision
        const fallback = decision ? isFallbackDecision(decision) : false
        // Honest outcome: only show a realized P&L when the field is truly
        // present and numeric — never a defaulted 0% that looks like break-even.
        const realizedPnl = trace.outcome
          ? toFiniteNum(getField(trace.outcome, FIELD_REALIZED_PNL_PCT))
          : null
        return (
          <div key={trace.trace_id} className={card}>
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : trace.trace_id)}
              aria-expanded={isOpen}
              className="flex w-full items-center justify-between gap-2 text-left"
            >
              <span className="flex items-center gap-2">
                {decision?.symbol && (
                  <span className="font-mono text-sm font-semibold text-foreground">
                    {decision.symbol}
                  </span>
                )}
                <span className="font-mono text-2xs text-muted-foreground">{trace.trace_id}</span>
              </span>
              <span className="flex items-center gap-2">
                {decision?.timestamp && (
                  <span className="text-2xs text-muted-foreground">
                    {formatTimeAgo(decision.timestamp)}
                  </span>
                )}
                {fallback && <FallbackTag />}
                {decision && (
                  <span className={cn(chip, actionTone(decision.action))}>
                    {decision.action.toUpperCase()}
                  </span>
                )}
                {trace.grade && <Grade grade={trace.grade.grade} />}
              </span>
            </button>
            {isOpen && (
              <div className="mt-3 space-y-2 border-t pt-3 text-xs">
                <Step name={COPY.steps.decision}>
                  {decision
                    ? `${decision.action.toUpperCase()} ${COPY.atScore} ${signed(
                        decision.confidence ?? decision.score,
                        2,
                      )}${
                        typeof decision.price === 'number' ? ` · ${formatUSD(decision.price)}` : ''
                      }`
                    : NO_DATA}
                </Step>
                <Step name={COPY.steps.reasoning}>{decision?.reasoning_summary || NO_DATA}</Step>
                <Step name={COPY.traceLlm}>
                  {decision == null
                    ? NO_DATA
                    : decision.llm_succeeded === false
                      ? `${COPY.traceRuleBased}${
                          decision.downgrade_reason ? ` · ${decision.downgrade_reason}` : ''
                        }`
                      : COPY.traceModelReasoned}
                </Step>
                <div className="flex gap-2">
                  <span className="w-28 shrink-0 text-muted-foreground">{COPY.tracePerception}</span>
                  <div className="flex-1">
                    <ToolChain decision={decision} />
                  </div>
                </div>
                {realizedPnl != null && (
                  <Step name={COPY.steps.outcome}>
                    {signed(realizedPnl)}
                    {CMD.pctSuffix}
                  </Step>
                )}
                {trace.grade && (
                  <Step name={COPY.steps.grade}>
                    {COPY.gradeOverall} {trace.grade.grade} · {COPY.gradeDirection}{' '}
                    {trace.grade.direction_grade} · {COPY.gradeRisk} {trace.grade.risk_grade} ·{' '}
                    {COPY.gradeExecution} {trace.grade.execution_grade} · {COPY.gradeTiming}{' '}
                    {trace.grade.timing_grade}
                  </Step>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
