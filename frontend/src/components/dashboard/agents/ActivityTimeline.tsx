'use client'

import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'
import type { ActivityItem, ActivityStage, ActivityTone } from '@/lib/activity-timeline'
import { EmptyState } from '@/components/ui/empty-state'
import { NO_DATA, UI_COPY } from '@/constants/copy'

// Eleven pipeline stages need eleven visually distinct dot hues — a
// categorical legend the four semantic Tone tokens cannot express.
const STAGE_META: Record<ActivityStage, { label: string; dot: string }> = {
  market: { label: 'Market', dot: 'bg-sky-500' }, // categorical-hue: stage legend
  signal: { label: 'Signal', dot: 'bg-cyan-500' }, // categorical-hue: stage legend
  decision: { label: 'Decision', dot: 'bg-indigo-500' }, // categorical-hue: stage legend
  execution: { label: 'Execution', dot: 'bg-violet-500' }, // categorical-hue: stage legend
  grade: { label: 'Grade', dot: 'bg-amber-500' }, // categorical-hue: stage legend
  proposal: { label: 'Proposal', dot: 'bg-fuchsia-500' }, // categorical-hue: stage legend
  risk: { label: 'Risk', dot: 'bg-rose-500' }, // categorical-hue: stage legend
  learning: { label: 'Learning', dot: 'bg-teal-500' }, // categorical-hue: stage legend
  notification: { label: 'Alert', dot: 'bg-muted-foreground' },
  agent: { label: 'Agent', dot: 'bg-emerald-500' }, // categorical-hue: stage legend
  system: { label: 'System', dot: 'bg-muted-foreground/70' },
}

// Row-title text colour per activity tone, resolved to the semantic tokens.
const ACTIVITY_TONE_TEXT: Record<ActivityTone, string> = {
  buy: 'text-success',
  sell: 'text-danger',
  good: 'text-success',
  bad: 'text-danger',
  warn: 'text-warning',
  neutral: 'text-foreground/80',
}

function timeLabel(ts: number): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? NO_DATA : d.toLocaleTimeString()
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const stage = STAGE_META[item.stage]
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-16 shrink-0 text-right font-mono text-2xs tabular-nums text-muted-foreground/70">
        {timeLabel(item.ts)}
      </span>
      <span className={cn('h-2 w-2 shrink-0 rounded-full', stage.dot)} aria-hidden />
      <span className="w-20 shrink-0 text-3xs font-semibold uppercase tracking-caps text-muted-foreground/70">
        {stage.label}
      </span>
      <span className={cn('truncate text-xs font-semibold', ACTIVITY_TONE_TEXT[item.tone])}>{item.title}</span>
      {item.detail ? (
        <span className="truncate font-mono text-2xs tabular-nums text-muted-foreground">
          {item.detail}
        </span>
      ) : null}
      {item.fallback ? (
        <span
          title={UI_COPY.decisions.ruleBasedRowTitle}
          className="ml-auto shrink-0 rounded bg-warning/15 px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-caps text-warning"
        >
          {UI_COPY.decisions.ruleBased}
        </span>
      ) : null}
    </div>
  )
}

/**
 * The live "story" of the pipeline — one chronological feed of what each stage
 * is doing, newest first. Built entirely from real store data by
 * `buildActivityTimeline`; renders an empty state until events arrive.
 */
export function ActivityTimeline({ items }: { items: ActivityItem[] }) {
  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>{UI_COPY.panels.liveActivity}</p>
        <span className={mutedClass}>
          {items.length > 0 ? `${items.length} ${UI_COPY.agentsPage.recentEvents}` : UI_COPY.agentsPage.idle}
        </span>
      </div>
      <p className={cn(mutedClass, 'mb-3')}>{UI_COPY.agentsPage.timelineDescription}</p>

      {items.length === 0 ? (
        <EmptyState message={UI_COPY.empty.activity} />
      ) : (
        <div className="max-h-96 divide-y overflow-y-auto">
          {items.map((item) => (
            <ActivityRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
