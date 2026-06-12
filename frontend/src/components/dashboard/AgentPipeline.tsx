'use client'

import { Fragment, type ComponentType } from 'react'
import { Activity, Brain, ChevronRight, FileSearch, Gauge, Radio, Settings2, Workflow, Zap } from 'lucide-react'

import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { UI_COPY } from '@/constants/copy'
import { cn } from '@/lib/utils'
import {
  buildPipelineStages,
  type AgentPipelineInput,
  type PipelineStageKey,
  type PipelineStageView,
  type StageTone,
} from '@/lib/agent-pipeline'

export type { PipelineAgentLike } from '@/lib/agent-pipeline'

const STAGE_ICONS: Record<PipelineStageKey, ComponentType<{ className?: string }>> = {
  market: Radio,
  signal: Activity,
  reasoning: Brain,
  execution: Zap,
  grade: Gauge,
  ic: Settings2,
  reflection: FileSearch,
  proposer: Workflow,
}

const TONE_STYLES: Record<StageTone, { dot: string; text: string; ring: string; label: string }> = {
  live: {
    dot: 'bg-success animate-pulse',
    text: 'text-success',
    ring: 'border-success/40 bg-success/5',
    label: UI_COPY.pipeline.toneLive,
  },
  idle: {
    dot: 'bg-warning',
    text: 'text-warning',
    ring: '',
    label: UI_COPY.pipeline.toneIdle,
  },
  stale: {
    dot: 'bg-warning',
    text: 'text-warning',
    ring: 'border-warning/40 bg-warning/5',
    label: UI_COPY.pipeline.toneStale,
  },
  error: {
    dot: 'bg-danger',
    text: 'text-danger',
    ring: 'border-danger/40 bg-danger/5',
    label: UI_COPY.pipeline.toneError,
  },
  none: {
    dot: 'bg-muted-foreground/40',
    text: 'text-muted-foreground/70',
    ring: '',
    label: UI_COPY.pipeline.toneWaiting,
  },
}

function StageCard({ stage }: { stage: PipelineStageView }) {
  const tone = TONE_STYLES[stage.tone]
  const Icon = STAGE_ICONS[stage.key]
  return (
    <div className={cn('flex w-[150px] shrink-0 flex-col gap-1 rounded-lg border px-3 py-3 sm:w-[160px]', tone.ring)}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5 text-muted-foreground/70" aria-hidden />
          <span className="text-3xs font-semibold uppercase tracking-caps text-muted-foreground">
            {stage.label}
          </span>
        </span>
        <span className={cn('h-2 w-2 shrink-0 rounded-full', tone.dot)} />
      </div>

      {stage.waitingHint ? (
        // A learning stage with 0 output and no closed trades is waiting on
        // input, not broken — a bare "0" here reads as a failure.
        <p className="flex min-h-8 items-center text-2xs italic leading-snug text-muted-foreground/70">
          {stage.waitingHint}
        </p>
      ) : (
        <div className="flex items-baseline gap-1">
          <span className="font-mono text-2xl font-bold tabular-nums text-foreground">
            {stage.count.toLocaleString()}
          </span>
          <span className="text-3xs font-medium text-muted-foreground/70">{stage.unit}</span>
        </div>
      )}

      <p className="text-xs font-semibold text-foreground/80">{stage.agent}</p>
      <p className="text-3xs leading-snug text-muted-foreground">{stage.does}</p>

      <div className="mt-auto flex items-center justify-between gap-1 pt-1">
        <span className={cn('text-3xs font-semibold uppercase tracking-caps', tone.text)}>{tone.label}</span>
        {stage.fact ? (
          <span className="truncate font-mono text-3xs text-muted-foreground" title={stage.fact}>
            {stage.fact}
          </span>
        ) : null}
      </div>
    </div>
  )
}

export function AgentPipeline(props: AgentPipelineInput) {
  const stages = buildPipelineStages(props)
  const liveCount = stages.filter((stage) => stage.tone === 'live').length

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>{UI_COPY.pipeline.title}</p>
        <span className={mutedClass}>
          {liveCount} of {stages.length} {UI_COPY.pipeline.stagesLive}
        </span>
      </div>
      <p className={cn(mutedClass, 'mb-3')}>{UI_COPY.pipeline.description}</p>

      <div className="flex items-stretch gap-1.5 overflow-x-auto pb-2">
        {stages.map((stage, index) => (
          <Fragment key={stage.key}>
            <StageCard stage={stage} />
            {index < stages.length - 1 ? (
              <div className="flex shrink-0 items-center">
                <ChevronRight aria-hidden className="h-4 w-4 text-muted-foreground/40" />
              </div>
            ) : null}
          </Fragment>
        ))}
      </div>

      <p className={cn(mutedClass, 'mt-1 flex items-center gap-1.5')}>
        <span aria-hidden className="text-sm leading-none">
          ↺
        </span>
        {UI_COPY.pipeline.loopNote}
      </p>
    </div>
  )
}
