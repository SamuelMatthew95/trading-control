'use client'

import type { ReactNode } from 'react'
import { Check, X } from 'lucide-react'

import { cn } from '@/lib/utils'
import { cardClass, chipClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { TONE_BADGE_OUTLINED } from '@/lib/design/sentiment'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { formatPercent, formatTimeAgo, formatUSD } from '@/lib/formatters'
import { actionTone, isFallbackDecision } from '@/lib/cognitive'
import { extractToolInvocations, summarizeToolOutputs } from '@/lib/decision-tools'
import { gradeTone } from '@/lib/grade-colors'
import type { DecisionPayload } from '@/types/cognitive'

// Copy roots shared by every cognitive panel.
export const COPY = UI_COPY.cognitive
export const CMD = COPY.cmd

// Shared dual-theme surface recipes (one home, imported by each panel).
export const card = cardClass
export const chip = chipClass
export const label = sectionTitleClass
export const pageShell = 'min-h-screen bg-background px-3 py-4 text-foreground sm:px-4'
export const subTableHeadClass =
  'bg-muted/60 text-3xs uppercase tracking-caps text-muted-foreground'

/** Outlined chip for an agent health status (healthy → success, else neutral). */
export const healthChip = (status: string): string =>
  status === 'healthy' ? TONE_BADGE_OUTLINED.success : TONE_BADGE_OUTLINED.neutral

/** Letter-grade chip (A–F categorical palette via gradeTone). */
export function Grade({ grade }: { grade: string | null | undefined }) {
  return <span className={cn(chip, gradeTone(grade))}>{grade || UI_COPY.learning.notRated}</span>
}

/** Labelled key/value row inside an expanded trace. */
export function Step({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="w-28 shrink-0 text-muted-foreground">{name}</span>
      <span className="min-w-0 break-words text-foreground/80">{children}</span>
    </div>
  )
}

/** "Rule-based fallback" warning tag — shown when the reasoning LLM didn't run. */
export function FallbackTag() {
  return (
    <span
      title={CMD.ruleBasedTitle}
      className="rounded-full bg-warning/15 px-2 py-0.5 text-3xs font-semibold uppercase tracking-caps text-warning"
    >
      {CMD.ruleBasedTag}
    </span>
  )
}

/** The reasoning chain (tool ledger) the decision exercised — real perception. */
export function ToolChain({ decision }: { decision: DecisionPayload | null }) {
  const tools = decision ? extractToolInvocations({ tools_used: decision.tools_used }) : []
  if (tools.length === 0) {
    return <p className="text-xs text-muted-foreground">{CMD.noTools}</p>
  }
  return (
    <div className="space-y-1">
      {tools.map((tool, i) => {
        const outputs = summarizeToolOutputs(tool.outputs)
        const failed = tool.success === false
        return (
          <div
            key={i}
            className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-2xs tabular-nums"
          >
            {failed ? (
              <X className="h-3 w-3 shrink-0 text-danger" aria-hidden />
            ) : (
              <Check className="h-3 w-3 shrink-0 text-success" aria-hidden />
            )}
            <span className="text-foreground/80">{tool.name ?? UI_COPY.decisions.toolFallback}</span>
            {typeof tool.latency_ms === 'number' && (
              <span className="text-muted-foreground/70">
                {tool.latency_ms.toFixed(0)}
                {CMD.msSuffix}
              </span>
            )}
            {outputs && (
              <span className="min-w-0 break-words text-muted-foreground">· {outputs}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Full reasoning card for one decision: action, symbol, confidence, the human
 *  summary, the rule-based-fallback flag, and the real perception chain. */
export function DecisionReasoningCard({
  decision,
  title,
}: {
  decision: DecisionPayload
  title: string
}) {
  const fallback = isFallbackDecision(decision)
  const conf = decision.confidence
  return (
    <div className={card}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className={label}>{title}</div>
        {fallback && <FallbackTag />}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn(chip, actionTone(decision.action))}>{decision.action.toUpperCase()}</span>
        <span className="font-mono text-sm font-semibold text-foreground">
          {decision.symbol ?? NO_DATA}
        </span>
        {typeof decision.price === 'number' && (
          <span className="font-mono text-xs text-muted-foreground">{formatUSD(decision.price)}</span>
        )}
        <span className="text-muted-foreground/50">·</span>
        <span className="font-mono text-xs text-foreground/70">
          {formatPercent(conf, { decimals: 0 })}
        </span>
        {decision.timestamp && (
          <>
            <span className="text-muted-foreground/50">·</span>
            <span className="text-xs text-muted-foreground">
              {formatTimeAgo(decision.timestamp)}
            </span>
          </>
        )}
      </div>
      {decision.reasoning_summary && (
        <p className="mt-2 text-sm text-foreground/80">{decision.reasoning_summary}</p>
      )}
      <div className="mt-3 rounded-md border bg-muted/40 p-2">
        <p className="mb-1 text-3xs font-semibold uppercase tracking-caps text-muted-foreground/70">
          {CMD.perceptionChain}
        </p>
        <ToolChain decision={decision} />
      </div>
    </div>
  )
}
