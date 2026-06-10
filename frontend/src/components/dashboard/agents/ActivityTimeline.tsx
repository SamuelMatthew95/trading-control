'use client'

import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { cn } from '@/lib/utils'
import type { ActivityItem, ActivityStage, ActivityTone } from '@/lib/activity-timeline'
import { EmptyState } from '@/components/ui/empty-state'

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
  notification: { label: 'Alert', dot: 'bg-slate-400' },
  agent: { label: 'Agent', dot: 'bg-emerald-500' }, // categorical-hue: stage legend
  system: { label: 'System', dot: 'bg-slate-500' },
}

// Row-title text colour per activity tone, resolved to the semantic tokens.
const ACTIVITY_TONE_TEXT: Record<ActivityTone, string> = {
  buy: 'text-success',
  sell: 'text-danger',
  good: 'text-success',
  bad: 'text-danger',
  warn: 'text-warning',
  neutral: 'text-slate-800 dark:text-slate-200',
}

function timeLabel(ts: number): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? '--' : d.toLocaleTimeString()
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const stage = STAGE_META[item.stage]
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-16 shrink-0 text-right font-mono text-[11px] tabular-nums text-slate-400 dark:text-slate-500">
        {timeLabel(item.ts)}
      </span>
      <span className={cn('h-2 w-2 shrink-0 rounded-full', stage.dot)} aria-hidden />
      <span className="w-20 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
        {stage.label}
      </span>
      <span className={cn('truncate text-xs font-semibold', ACTIVITY_TONE_TEXT[item.tone])}>{item.title}</span>
      {item.detail ? (
        <span className="truncate font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400">
          {item.detail}
        </span>
      ) : null}
      {item.fallback ? (
        <span
          title="LLM unavailable — rule-based fallback, not model reasoning."
          className="ml-auto shrink-0 rounded bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning"
        >
          rule-based
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
        <p className={sectionTitleClass}>Live Activity</p>
        <span className={mutedClass}>{items.length > 0 ? `${items.length} recent events` : 'idle'}</span>
      </div>
      <p className={cn(mutedClass, 'mb-3')}>
        What the pipeline is doing right now — every signal, decision, execution and alert in the
        order it happened.
      </p>

      {items.length === 0 ? (
        <EmptyState message="No activity yet — events stream in here as the pipeline runs." />
      ) : (
        <div className="max-h-96 divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800/60">
          {items.map((item) => (
            <ActivityRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
