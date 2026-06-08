'use client'

import { useEffect, useState } from 'react'

import { api } from '@/lib/apiClient'
import { agentDisplayName } from '@/constants/agents'
import { agentDetailPath, type AgentDetail } from '@/lib/agent-performance'
import { gradeBg, tierBadge, tierLabel } from '@/lib/grade-colors'
import { sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { TONE_TEXT, type Tone } from '@/lib/design/sentiment'
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
        <span className="text-slate-600 dark:text-slate-300">{label}</span>
        {available ? (
          <span className="font-mono tabular-nums text-slate-500 dark:text-slate-400">
            {pct}% · w{weight.toFixed(2)}
          </span>
        ) : (
          <span className="font-mono text-slate-400 dark:text-slate-600" title="no telemetry for this dimension yet">
            no data
          </span>
        )}
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
        {available && (
          <div
            className={cn(
              'h-full rounded-full',
              value >= 0.8 ? 'bg-emerald-500' : value >= 0.5 ? 'bg-amber-500' : 'bg-rose-500',
            )}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
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
          setError('Failed to load agent detail')
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [name])

  const grade = data?.grade ?? null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={sectionTitleClass}>{agentDisplayName(name)}</p>
            <p className={cn(mutedClass, 'font-mono')}>{name}</p>
          </div>
          <div className="flex items-center gap-2">
            {data && (
              <>
                <span
                  className={cn(
                    'rounded-md border px-2 py-0.5 text-sm font-bold',
                    gradeBg(grade),
                  )}
                >
                  {grade ?? '—'}
                </span>
                <span
                  className={cn(
                    'rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide',
                    tierBadge(data.tier),
                  )}
                >
                  {data.promoted && <span className="mr-1">★</span>}
                  {tierLabel(data.tier)}
                </span>
              </>
            )}
            <button
              onClick={onClose}
              className="text-xl font-bold leading-none text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        {loading && <p className={mutedClass}>Loading…</p>}
        {error && <p className="text-sm text-rose-500">{error}</p>}

        {data && (
          <div className="space-y-5">
            {/* Headline metrics */}
            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                <p className="font-mono text-lg tabular-nums text-slate-900 dark:text-slate-100">
                  {data.score_pct == null ? '—' : `${data.score_pct}%`}
                </p>
                <p className={mutedClass}>score</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                <p className="font-mono text-lg tabular-nums text-slate-900 dark:text-slate-100">
                  {data.event_count.toLocaleString()}
                </p>
                <p className={mutedClass}>events</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                <p className="font-mono text-lg tabular-nums text-slate-900 dark:text-slate-100">
                  {data.completed_runs}/{data.total_runs}
                </p>
                <p className={mutedClass}>runs ok</p>
              </div>
            </div>

            {/* Promotion standing */}
            <div className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-600 dark:text-slate-300">
                  A/A+ streak: <span className="font-mono">{data.grade_streak}</span>
                </span>
                <span className="text-slate-600 dark:text-slate-300">
                  trust <span className="font-mono">{data.trust.toFixed(2)}</span>
                  {data.target_trust !== data.trust && (
                    <span className="text-slate-400">
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
                        title={`${h.grade ?? '—'} · ${h.timestamp}`}
                        className={cn(
                          'inline-block h-4 w-2 rounded-sm',
                          gradeBg(h.grade),
                        )}
                      />
                    ))}
                </div>
              )}
            </div>

            {/* Dimensions */}
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>Grade Breakdown</p>
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
                <p className={cn(sectionTitleClass, 'mb-2')}>Learnings</p>
                <ul className="space-y-1.5">
                  {data.learnings.map((l, i) => (
                    <li key={`learning-${i}`} className="flex items-start gap-2 text-xs">
                      <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-current', toneClass(l.tone))} />
                      <span className="text-slate-700 dark:text-slate-300">{l.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Heartbeat */}
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>Heartbeat</p>
              <p className="font-mono text-xs text-slate-600 dark:text-slate-400">
                {String(data.heartbeat.status ?? '—')}
                {data.heartbeat.seconds_ago != null && ` · ${data.heartbeat.seconds_ago}s ago`}
                {data.heartbeat.last_event ? ` · last: ${data.heartbeat.last_event}` : ''}
              </p>
            </div>

            {/* Recent activity — what the agent actually did */}
            <div>
              <p className={cn(sectionTitleClass, 'mb-2')}>Recent Activity</p>
              {data.recent_activity.length === 0 ? (
                <p className={mutedClass}>No recent runs recorded.</p>
              ) : (
                <div className="space-y-1">
                  {data.recent_activity.map((a, i) => (
                    <div
                      key={`activity-${a.trace_id ?? i}`}
                      className="flex items-center justify-between gap-2 rounded border border-slate-200 px-2 py-1 font-mono text-[11px] text-slate-600 dark:border-slate-800 dark:text-slate-400"
                    >
                      <span className="truncate">
                        {a.trace_id ? a.trace_id.slice(0, 12) : '—'}
                        {a.symbol ? ` · ${a.symbol}` : ''}
                      </span>
                      <span className="shrink-0 text-slate-500 dark:text-slate-500">
                        {String(a.status ?? '')}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <p className={cn(mutedClass, 'text-right')}>
              data source: {data.mode === 'memory' ? 'in-memory (DB down)' : 'database'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
