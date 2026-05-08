'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForPipelineStage } from '@/lib/state'
import { formatTimeAgo } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type { PipelineStageView } from '@/lib/types'

interface LearningPipelineStatusPanelProps {
  stages: readonly PipelineStageView[]
}

export function LearningPipelineStatusPanel({ stages }: LearningPipelineStatusPanelProps) {
  return (
    <TerminalCard>
      <SectionHeader title="Learning Pipeline Status" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {stages.map((stage) => {
          const tone = toneForPipelineStage(stage.status)
          return (
            <div
              key={stage.key}
              className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800"
            >
              <p className={UI_TEXT.muted}>{stage.label}</p>
              <p
                className={cn(
                  'mt-1 text-xs font-semibold uppercase tracking-wide',
                  TONE_CLASSES[tone].text,
                )}
              >
                {stage.status}
              </p>
              <p className={cn(UI_TEXT.cell, 'mt-1')}>{stage.count}</p>
              <p className="mt-1 text-[11px] font-mono text-slate-500">
                {stage.lastRun ? `last ${formatTimeAgo(stage.lastRun)}` : 'No runs yet'}
              </p>
            </div>
          )
        })}
      </div>
    </TerminalCard>
  )
}
