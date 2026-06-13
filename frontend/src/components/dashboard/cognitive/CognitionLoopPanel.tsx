'use client'

import { Fragment } from 'react'
import { ArrowRight, Repeat } from 'lucide-react'

import { cn } from '@/lib/utils'
import { PromptEvolutionPanel } from '@/components/dashboard/PromptEvolutionPanel'
import { ToolGovernancePanel } from '@/components/dashboard/ToolGovernancePanel'

import { card, COPY, label } from './cognitive-ui'

// The self-evolving cognition loop, stage by stage (mirrors CLAUDE.md).
const LOOP_STAGES = COPY.loopStages

export function CognitionLoopPanel() {
  return (
    <div className="space-y-4">
      <div className={card}>
        <div className={cn(label, 'mb-3')}>{COPY.loopTitle}</div>
        <div className="flex flex-wrap items-center gap-2">
          {LOOP_STAGES.map((stage, i) => (
            <Fragment key={stage.label}>
              <div className="rounded-lg border px-3 py-1.5">
                <div className="text-sm font-medium text-foreground">{stage.label}</div>
                <div className="text-2xs text-muted-foreground">{stage.note}</div>
              </div>
              {i < LOOP_STAGES.length - 1 && (
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/70" aria-hidden />
              )}
            </Fragment>
          ))}
          <span className="ml-1 inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-2xs font-semibold text-muted-foreground">
            <Repeat className="h-3 w-3" aria-hidden /> {COPY.directiveEvolves}
          </span>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{COPY.loopDescription}</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2 lg:items-start">
        <PromptEvolutionPanel />
        <ToolGovernancePanel />
      </div>
    </div>
  )
}
