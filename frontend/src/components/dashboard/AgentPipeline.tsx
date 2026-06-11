'use client'

import { Fragment, type ComponentType } from 'react'
import { Activity, Brain, ChevronRight, FileSearch, Gauge, Radio, Settings2, Workflow, Zap } from 'lucide-react'

import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
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
    label: 'Live',
  },
  idle: {
    dot: 'bg-warning',
    text: 'text-warning',
    ring: 'border-slate-200 dark:border-slate-800',
    label: 'Idle',
  },
  stale: {
    dot: 'bg-warning',
    text: 'text-warning',
    ring: 'border-warning/40 bg-warning/5',
    label: 'Stale',
  },
  error: {
    dot: 'bg-danger',
    text: 'text-danger',
    ring: 'border-danger/40 bg-danger/5',
    label: 'Error',
  },
  none: {
    dot: 'bg-slate-300 dark:bg-slate-600',
    text: 'text-slate-400 dark:text-slate-500',
    ring: 'border-slate-200 dark:border-slate-800',
    label: 'Waiting',
  },
}

function StageCard({ stage }: { stage: PipelineStageView }) {
  const tone = TONE_STYLES[stage.tone]
  const Icon = STAGE_ICONS[stage.key]
  return (
    <div className={cn('flex w-[150px] shrink-0 flex-col gap-1 rounded-lg border px-3 py-3 sm:w-[160px]', tone.ring)}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
            {stage.label}
          </span>
        </span>
        <span className={cn('h-2 w-2 shrink-0 rounded-full', tone.dot)} />
      </div>

      {stage.waitingHint ? (
        // A learning stage with 0 output and no closed trades is waiting on
        // input, not broken — a bare "0" here reads as a failure.
        <p className="flex min-h-8 items-center text-[11px] italic leading-snug text-slate-400 dark:text-slate-500">
          {stage.waitingHint}
        </p>
      ) : (
        <div className="flex items-baseline gap-1">
          <span className="font-mono text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">
            {stage.count.toLocaleString()}
          </span>
          <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500">{stage.unit}</span>
        </div>
      )}

      <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">{stage.agent}</p>
      <p className="text-[10px] leading-snug text-slate-500 dark:text-slate-400">{stage.does}</p>

      <div className="mt-auto flex items-center justify-between gap-1 pt-1">
        <span className={cn('text-[10px] font-semibold uppercase tracking-wider', tone.text)}>{tone.label}</span>
        {stage.fact ? (
          <span className="truncate text-[10px] font-mono text-slate-500 dark:text-slate-400" title={stage.fact}>
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
        <p className={sectionTitleClass}>Agent Pipeline</p>
        <span className={mutedClass}>
          {liveCount} of {stages.length} stages live
        </span>
      </div>
      <p className={cn(mutedClass, 'mb-3')}>
        How data moves through the system — each box is an agent, the number is what it has produced.
      </p>

      <div className="flex items-stretch gap-1.5 overflow-x-auto pb-2">
        {stages.map((stage, index) => (
          <Fragment key={stage.key}>
            <StageCard stage={stage} />
            {index < stages.length - 1 ? (
              <div className="flex shrink-0 items-center">
                <ChevronRight aria-hidden className="h-4 w-4 text-slate-300 dark:text-slate-700" />
              </div>
            ) : null}
          </Fragment>
        ))}
      </div>

      <p className={cn(mutedClass, 'mt-1 flex items-center gap-1.5')}>
        <span aria-hidden className="text-sm leading-none">
          ↺
        </span>
        Grades and re-weighted factors loop back into Reasoning — that&apos;s how the system learns over time.
      </p>
    </div>
  )
}
