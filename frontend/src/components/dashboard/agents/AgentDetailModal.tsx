'use client'

import { useEffect, useState } from 'react'

import { api } from '@/lib/apiClient'
import { agentDisplayName } from '@/constants/agents'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { agentDetailPath, type AgentDetail } from '@/lib/agent-performance'
import { gradeBg, tierBadge, tierLabel } from '@/lib/grade-colors'
import { meterFillClass } from '@/lib/dashboard-helpers'
import { sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { TONE_TEXT, type Tone } from '@/lib/design/sentiment'
import { Modal } from '@/components/ui/modal'
import { Meter } from '@/components/ui/meter'
import { MetricTile } from '@/components/ui/stat-tile'
import { LoadingState } from '@/components/ui/loading'
import { cn } from '@/lib/utils'

function toneClass(tone: string): string {
  return TONE_TEXT[(tone as Tone)] ?? TONE_TEXT.neutral
}

function DimensionBar({ label, value, weight, available }: {
  label: string
  value: number
  weight: number
  available: boolean
}) {
  const pct = Math.round(value * 100)
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-foreground/80">{label}</span>
        {available ? (
          <span className="font-mono tabular-nums text-muted-foreground">
            {pct}% · w{weight.toFixed(2)}
          </span>
        ) : (
          <span
            className="font-mono text-muted-foreground/60"
            title={UI_COPY.agentDetail.noTelemetryTitle}
          >
            {UI_COPY.agentDetail.noTelemetry}
          </span>
        )}
      </div>
      <Meter
        value={available ? pct : 0}
        label={label}
        fillClassName={meterFillClass(value)}
      />
    </div>
  )
}

export function AgentDetailModal({ name, onClose }: { name: string; onClose: () => void }) {
  const [data, setData] = useState<AgentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(api(agentDetailPath(name)))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => {
        if (!cancelled) {
          setData(d as AgentDetail)
          setLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(UI_COPY.agentDetail.loadError)
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [name])

  const grade = data?.grade ?? null

  return (
    <Modal
      onClose={onClose}
      title={agentDisplayName(name)}
      subtitle={
        <div className="flex flex-wrap items-center gap-2">
          <p className={cn(mutedClass, 'font-mono')}>{name}</p>
          {data && (
            <>
              <span className={cn('rounded-md border px-2 py-0.5 text-sm font-bold', gradeBg(grade))}>
                {grade ?? NO_DATA}
              </span>
              <span
                className={cn(
                  'rounded-md border px-2 py-0.5 text-2xs font-semibold uppercase tracking-caps',
                  tierBadge(data.tier),
                )}
              >
                {data.promoted && <span className="mr-1">★</span>}
                {tierLabel(data.tier)}
              </span>
            </>
          )}
        </div>
      }
    >
      {loading && <LoadingState />}
      {error && <p className="text-sm text-danger">{error}</p>}

      {data && (
        <div className="space-y-5">
          {/* Headline metrics */}
          <div className="grid grid-cols-3 gap-3">
            <MetricTile
              label={UI_COPY.agentDetail.score}
              value={data.score_pct == null ? NO_DATA : `${data.score_pct}%`}
            />
            <MetricTile label={UI_COPY.agentDetail.events} value={data.event_count.toLocaleString()} />
            <MetricTile
              label={UI_COPY.agentDetail.runsOk}
              value={`${data.completed_runs}/${data.total_runs}`}
            />
          </div>

          {/* Promotion standing */}
          <div className="rounded-lg border px-3 py-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-foreground/80">
                {UI_COPY.agentDetail.gradeStreak} <span className="font-mono">{data.grade_streak}</span>
              </span>
              <span className="text-foreground/80">
                {UI_COPY.agentDetail.trust} <span className="font-mono">{data.trust.toFixed(2)}</span>
                {data.target_trust !== data.trust && (
                  <span className="text-muted-foreground/70">
                    {' → '}
                    <span className="font-mono">{data.target_trust.toFixed(2)}</span>
                  </span>
                )}
              </span>
            </div>
            {data.history.length > 1 && (
              <div className="mt-2 flex items-center gap-1">
                {data.history
                  .slice()
                  .reverse()
                  .map((h, i) => (
                    <span
                      key={`hist-${i}`}
                      title={`${h.grade ?? NO_DATA} · ${h.timestamp}`}
                      className={cn('inline-block h-4 w-2 rounded-sm', gradeBg(h.grade))}
                    />
                  ))}
              </div>
            )}
          </div>

          {/* Dimensions */}
          <div>
            <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.agentDetail.gradeBreakdown}</p>
            <div className="space-y-2.5">
              {data.dimensions.map((d) => (
                <DimensionBar
                  key={d.key}
                  label={d.label}
                  value={d.value}
                  weight={d.weight}
                  available={d.data_available}
                />
              ))}
            </div>
          </div>

          {/* Learnings */}
          {data.learnings.length > 0 && (
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.agentDetail.learnings}</p>
              <ul className="space-y-1.5">
                {data.learnings.map((l, i) => (
                  <li key={`learning-${i}`} className="flex items-start gap-2 text-xs">
                    <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-current', toneClass(l.tone))} />
                    <span className="text-foreground/80">{l.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Heartbeat */}
          <div>
            <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.agentDetail.heartbeat}</p>
            <p className="font-mono text-xs text-foreground/70">
              {String(data.heartbeat.status ?? NO_DATA)}
              {data.heartbeat.seconds_ago != null && ` · ${data.heartbeat.seconds_ago}s ago`}
              {data.heartbeat.last_event ? ` · last: ${data.heartbeat.last_event}` : ''}
            </p>
          </div>

          {/* Recent activity — what the agent actually did */}
          <div>
            <p className={cn(sectionTitleClass, 'mb-2')}>{UI_COPY.agentDetail.recentActivity}</p>
            {data.recent_activity.length === 0 ? (
              <p className={mutedClass}>{UI_COPY.agentDetail.noRecentRuns}</p>
            ) : (
              <div className="space-y-1">
                {data.recent_activity.map((a, i) => (
                  <div
                    key={`activity-${a.trace_id ?? i}`}
                    className="flex items-center justify-between gap-2 rounded border px-2 py-1 font-mono text-2xs text-foreground/70"
                  >
                    <span className="truncate">
                      {a.trace_id ? a.trace_id.slice(0, 12) : NO_DATA}
                      {a.symbol ? ` · ${a.symbol}` : ''}
                    </span>
                    <span className="shrink-0 text-muted-foreground">{String(a.status ?? '')}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <p className={cn(mutedClass, 'text-right')}>
            {UI_COPY.agentDetail.dataSource}{' '}
            {data.mode === 'memory' ? UI_COPY.agentDetail.sourceMemory : UI_COPY.agentDetail.sourceDatabase}
          </p>
        </div>
      )}
    </Modal>
  )
}
