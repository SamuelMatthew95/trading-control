'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, toneForPipelineStage } from '@/lib/state'
import { formatTimeAgo } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { INNER_TILE, SUB_PANEL_GRID_5, TINY_MONO } from '@/lib/styles'
import type { PipelineStageView } from '@/lib/types'

interface LearningPipelineStatusPanelProps {
  stages: readonly PipelineStageView[]
}

const STAGE_STATUS_TEXT = 'mt-1 text-xs font-semibold uppercase tracking-wide'

function lastRunLabel(stage: PipelineStageView): string {
  return stage.lastRun ? `last ${formatTimeAgo(stage.lastRun)}` : 'No runs yet'
}

function PipelineStageTile(props: { stage: PipelineStageView }) {
  const { stage } = props
  const tone = toneForPipelineStage(stage.status)
  return (
    <div className={INNER_TILE}>
      <p className={UI_TEXT.muted}>{stage.label}</p>
      <p className={cn(STAGE_STATUS_TEXT, TONE_CLASSES[tone].text)}>{stage.status}</p>
      <p className={cn(UI_TEXT.cell, 'mt-1')}>{stage.count}</p>
      <p className={cn('mt-1', TINY_MONO)}>{lastRunLabel(stage)}</p>
    </div>
  )
}

export function LearningPipelineStatusPanel(props: LearningPipelineStatusPanelProps) {
  return (
    <TerminalCard>
      <SectionHeader title="Learning Pipeline Status" />
      <div className={SUB_PANEL_GRID_5}>
        {props.stages.map((stage) => (
          <PipelineStageTile key={stage.key} stage={stage} />
        ))}
      </div>
    </TerminalCard>
  )
}
