'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TradeEvaluation {
  id: string
  trade_eval_id: string
  symbol: string | null
  side: string | null
  pnl: number | null
  pnl_percent: number | null
  entry_quality: number | null
  exit_quality: number | null
  timing_score: number | null
  signal_alignment: number | null
  risk_reward: number | null
  overall_score: number | null
  grade: string | null
  confidence: number | null
  mistakes: string[]
  strengths: string[]
  created_at: string | null
}

interface TradesResponse {
  trades: TradeEvaluation[]
  total: number
  mode: string
}

interface LearningMetrics {
  total_trades: number
  win_rate: number
  avg_return: number
  sharpe_ratio: number
  max_drawdown: number
  avg_score: number
  score_trend: string
  consistency: number
  mode: string
  timestamp: string
}

interface MistakeCluster {
  type: string
  frequency: number
  impact: number
  count: number
}

interface Reflection {
  id?: string
  patterns: string[]
  mistake_clusters: MistakeCluster[]
  recommendations: string[]
  trades_analyzed: number | null
  win_rate: number | null
  avg_return: number | null
  confidence: number | null
  created_at: string | null
}

interface ReflectionsResponse {
  reflections: Reflection[]
  total: number
  mode: string
}

interface Strategy {
  id: string
  rules: Record<string, unknown>
  description: string | null
  expected_improvement: number | null
  status: string | null
  reflection_id: string | null
  created_at: string | null
}

interface StrategiesResponse {
  strategies: Strategy[]
  total: number
  mode: string
}

interface PipelineStage {
  status: string
  jobs_processed: number
  last_run: string | null
  error_count: number
}

interface PipelineStatus {
  mode: string
  timestamp: string
  stages: {
    scoring: PipelineStage
    reflection: PipelineStage
    strategy_proposer: PipelineStage
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const REFRESH_MS = 15_000

const gradeColor = (grade: string | null): string => {
  switch (grade) {
    case 'A': return 'text-emerald-600 dark:text-emerald-500'
    case 'B': return 'text-green-600 dark:text-green-400'
    case 'C': return 'text-amber-600 dark:text-amber-500'
    case 'D': return 'text-orange-600 dark:text-orange-500'
    case 'F': return 'text-rose-600 dark:text-rose-500'
    default: return 'text-slate-500 dark:text-slate-400'
  }
}

const gradeBg = (grade: string | null): string => {
  switch (grade) {
    case 'A': return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30'
    case 'B': return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-500/10 dark:text-green-400 dark:border-green-500/30'
    case 'C': return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/30'
    case 'D': return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-400 dark:border-orange-500/30'
    case 'F': return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/30'
    default: return 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/30'
  }
}

const fmtPct = (n: number | null | undefined, decimals = 1): string =>
  n == null ? '--' : `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`

const fmtUSD = (n: number | null | undefined): string => {
  if (n == null) return '--'
  const abs = Math.abs(n)
  const fmt = abs >= 1000
    ? abs.toLocaleString('en-US', { maximumFractionDigits: 0 })
    : abs.toFixed(2)
  return `${n < 0 ? '-' : '+'}$${fmt}`
}

const fmtScore = (n: number | null | undefined): string =>
  n == null ? '--' : (n * 100).toFixed(0) + '%'

const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleTimeString()
  } catch {
    return '--'
  }
}

const trendIcon = (trend: string): string => {
  if (trend === 'improving') return '▲'
  if (trend === 'declining') return '▼'
  return '→'
}

const trendColor = (trend: string): string => {
  if (trend === 'improving') return 'text-emerald-500'
  if (trend === 'declining') return 'text-rose-500'
  return 'text-slate-500 dark:text-slate-400'
}

const stageColor = (status: string): string =>
  status === 'active' ? 'text-emerald-600 dark:text-emerald-500' : status === 'failed' ? 'text-rose-600 dark:text-rose-500' : 'text-slate-500 dark:text-slate-400'

// ScoreBar — a horizontal bar showing a [0,1] score
function ScoreBar({ value, color }: { value: number | null; color?: string }) {
  const pct = value == null ? 0 : Math.round(value * 100)
  const bg = color || (pct >= 75 ? 'bg-emerald-500' : pct >= 60 ? 'bg-amber-400' : 'bg-rose-500')
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-slate-200 dark:bg-slate-700">
        <div className={`h-1.5 rounded-full ${bg}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-10 text-right text-xs font-mono text-slate-500">{pct}%</span>
    </div>
  )
}

// Panel wrapper
function Panel({ title, children, badge }: { title: string; children: React.ReactNode; badge?: string }) {
  return (
    <div className="rounded-xl border border-slate-300 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          {title}
        </p>
        {badge && (
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-500">
            {badge}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

function ModeBanner({ mode }: { mode: string }) {
  if (mode === 'db') return null
  return (
    <div className="mb-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs text-amber-700 dark:bg-amber-500/10 dark:border-amber-500/30 dark:text-amber-400">
      Running in memory mode — data is transient and will reset on restart
    </div>
  )
}

// ---------------------------------------------------------------------------
// Trade Detail Modal
// ---------------------------------------------------------------------------

function TradeDetailModal({
  trade,
  onClose,
}: {
  trade: TradeEvaluation
  onClose: () => void
}) {
  const dims: { label: string; key: keyof TradeEvaluation }[] = [
    { label: 'Entry Quality', key: 'entry_quality' },
    { label: 'Exit Quality', key: 'exit_quality' },
    { label: 'Risk/Reward', key: 'risk_reward' },
    { label: 'Signal Alignment', key: 'signal_alignment' },
    { label: 'Timing Score', key: 'timing_score' },
    { label: 'Overall Score', key: 'overall_score' },
  ]
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
              {trade.symbol ?? '--'} <span className="text-slate-500 dark:text-slate-400">{trade.side?.toUpperCase()}</span>
            </p>
            <p className="text-xs text-slate-500">{fmtTime(trade.created_at)}</p>
          </div>
          <div className="text-right">
            <span className={`text-3xl font-black font-mono ${gradeColor(trade.grade)}`}>
              {trade.grade ?? '--'}
            </span>
            <p className="text-xs font-mono text-slate-500 dark:text-slate-400">{fmtScore(trade.overall_score)}</p>
          </div>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-3 text-xs font-mono">
          <div>
            <p className="text-slate-500">P&L</p>
            <p className={`font-bold ${(trade.pnl ?? 0) >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
              {fmtUSD(trade.pnl)}
            </p>
          </div>
          <div>
            <p className="text-slate-500">Return</p>
            <p className={`font-bold ${(trade.pnl_percent ?? 0) >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
              {fmtPct(trade.pnl_percent)}
            </p>
          </div>
        </div>

        <div className="mb-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Score Breakdown</p>
          {dims.map((d) => (
            <div key={d.key}>
              <p className="mb-0.5 text-xs text-slate-500 dark:text-slate-400">{d.label}</p>
              <ScoreBar value={trade[d.key] as number | null} />
            </div>
          ))}
        </div>

        {trade.mistakes.length > 0 && (
          <div className="mb-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-400">Mistakes</p>
            <div className="flex flex-wrap gap-1">
              {trade.mistakes.map((m) => (
                <span key={m} className="rounded bg-rose-50 border border-rose-200 px-2 py-0.5 text-xs text-rose-700 dark:bg-rose-500/10 dark:border-rose-500/30 dark:text-rose-400">
                  {m.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          </div>
        )}

        {trade.strengths.length > 0 && (
          <div className="mb-4">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">Strengths</p>
            <div className="flex flex-wrap gap-1">
              {trade.strengths.map((s) => (
                <span key={s} className="rounded bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-xs text-emerald-700 dark:bg-emerald-500/10 dark:border-emerald-500/30 dark:text-emerald-400">
                  {s.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          </div>
        )}

        <button
          onClick={onClose}
          className="w-full rounded-lg bg-slate-100 py-2 text-sm text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          Close
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Panel: Trade Table
// ---------------------------------------------------------------------------

function TradeTablePanel({
  trades,
  total,
  mode,
  onSelect,
}: {
  trades: TradeEvaluation[]
  total: number
  mode: string
  onSelect: (t: TradeEvaluation) => void
}) {
  return (
    <Panel title="Trade Evaluations" badge={`${total} total`}>
      <ModeBanner mode={mode} />
      {trades.length === 0 ? (
        <p className="text-xs text-slate-500">No scored trades yet — evaluations appear once trades close.</p>
      ) : (
        <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-300 dark:border-slate-800">
          <table className="w-full text-xs font-mono">
            <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800/90">
              <tr className="text-left text-slate-500">
                <th className="p-2">Symbol</th>
                <th className="p-2">Side</th>
                <th className="p-2 text-right">P&L</th>
                <th className="p-2 text-right">Score</th>
                <th className="p-2 text-center">Grade</th>
                <th className="p-2 text-right">Entry Q</th>
                <th className="p-2 text-right">Exit Q</th>
                <th className="p-2 text-right">When</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr
                  key={t.id || t.trade_eval_id}
                  className="cursor-pointer border-t border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60"
                  onClick={() => onSelect(t)}
                >
                  <td className="p-2 font-semibold">{t.symbol ?? '--'}</td>
                  <td className={`p-2 ${t.side === 'buy' ? 'text-emerald-500' : 'text-rose-500'}`}>
                    {t.side?.toUpperCase() ?? '--'}
                  </td>
                  <td className={`p-2 text-right ${(t.pnl ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                    {fmtUSD(t.pnl)}
                  </td>
                  <td className="p-2 text-right">{fmtScore(t.overall_score)}</td>
                  <td className="p-2 text-center">
                    <span className={`rounded border px-1.5 py-0.5 text-xs font-bold ${gradeBg(t.grade)}`}>
                      {t.grade ?? '--'}
                    </span>
                  </td>
                  <td className="p-2 text-right text-slate-500">{fmtScore(t.entry_quality)}</td>
                  <td className="p-2 text-right text-slate-500">{fmtScore(t.exit_quality)}</td>
                  <td className="p-2 text-right text-slate-400">{fmtTime(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Panel: Agent Performance Dashboard
// ---------------------------------------------------------------------------

function AgentPerformancePanel({ metrics }: { metrics: LearningMetrics | null }) {
  if (!metrics) {
    return (
      <Panel title="Agent Performance">
        <p className="text-xs text-slate-500">Loading metrics…</p>
      </Panel>
    )
  }

  const tiles = [
    {
      label: 'Win Rate',
      value: fmtPct(metrics.win_rate * 100, 1),
      color: metrics.win_rate >= 0.5 ? 'text-emerald-500' : 'text-rose-500',
    },
    {
      label: 'Avg Return',
      value: fmtPct(metrics.avg_return, 2),
      color: metrics.avg_return >= 0 ? 'text-emerald-500' : 'text-rose-500',
    },
    {
      label: 'Sharpe',
      value: metrics.sharpe_ratio?.toFixed(2) ?? '--',
      color: metrics.sharpe_ratio >= 1 ? 'text-emerald-500' : metrics.sharpe_ratio >= 0 ? 'text-amber-600 dark:text-amber-400' : 'text-rose-500',
    },
    {
      label: 'Max Drawdown',
      value: fmtPct(metrics.max_drawdown * 100, 1),
      color: 'text-rose-400',
    },
    {
      label: 'Avg Score',
      value: fmtScore(metrics.avg_score),
      color: metrics.avg_score >= 0.6 ? 'text-emerald-500' : 'text-amber-600 dark:text-amber-400',
    },
    {
      label: 'Consistency',
      value: fmtScore(metrics.consistency),
      color: metrics.consistency >= 0.7 ? 'text-emerald-500' : 'text-amber-600 dark:text-amber-400',
    },
  ]

  return (
    <Panel title="Agent Performance" badge={`${metrics.total_trades} trades`}>
      <ModeBanner mode={metrics.mode} />
      <div className="mb-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg border border-slate-300 bg-slate-50 p-2 dark:border-slate-800 dark:bg-transparent">
            <p className="text-xs text-slate-500 dark:text-slate-400">{t.label}</p>
            <p className={`text-sm font-mono font-bold ${t.color}`}>{t.value}</p>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800/60">
        <span className="text-xs text-slate-500">Score trend:</span>
        <span className={`text-sm font-bold font-mono ${trendColor(metrics.score_trend)}`}>
          {trendIcon(metrics.score_trend)} {metrics.score_trend}
        </span>
      </div>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Panel: Reflection
// ---------------------------------------------------------------------------

function ReflectionPanel({ reflection, mode }: { reflection: Reflection | null; mode: string }) {
  return (
    <Panel title="Latest Reflection">
      <ModeBanner mode={mode} />
      {!reflection ? (
        <p className="text-xs text-slate-500">No reflections yet — runs after every {' '}
          <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">N</code> trades.</p>
      ) : (
        <div className="space-y-3">
          <div className="flex gap-4 text-xs font-mono">
            {reflection.trades_analyzed != null && (
              <span className="text-slate-500 dark:text-slate-400">trades: <b className="text-slate-700 dark:text-slate-200">{reflection.trades_analyzed}</b></span>
            )}
            {reflection.win_rate != null && (
              <span className="text-slate-500 dark:text-slate-400">win rate: <b className={reflection.win_rate >= 0.5 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>{fmtPct(reflection.win_rate * 100, 0)}</b></span>
            )}
            {reflection.confidence != null && (
              <span className="text-slate-500 dark:text-slate-400">confidence: <b className="text-slate-700 dark:text-slate-200">{fmtPct(reflection.confidence * 100, 0)}</b></span>
            )}
          </div>

          {reflection.patterns.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">Patterns</p>
              <ul className="space-y-1">
                {reflection.patterns.slice(0, 5).map((p, i) => (
                  <li key={i} className="flex gap-2 text-xs text-slate-600 dark:text-slate-400">
                    <span className="text-amber-600 dark:text-amber-400 shrink-0">→</span>
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {reflection.mistake_clusters.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">Mistake Clusters</p>
              <div className="space-y-1.5">
                {reflection.mistake_clusters.slice(0, 4).map((c, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="w-32 font-mono text-slate-600 dark:text-slate-300">{c.type.replace(/_/g, ' ')}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-slate-200 dark:bg-slate-700">
                      <div
                        className="h-1.5 rounded-full bg-rose-500"
                        style={{ width: `${Math.round(c.frequency * 100)}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-slate-500 dark:text-slate-400">{fmtPct(c.frequency * 100, 0)}</span>
                    <span className={`w-16 text-right font-mono ${c.impact < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                      {fmtUSD(c.impact)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {reflection.recommendations.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">Recommendations</p>
              <ul className="space-y-1">
                {reflection.recommendations.slice(0, 3).map((r, i) => (
                  <li key={i} className="flex gap-2 text-xs text-slate-600 dark:text-slate-400">
                    <span className="text-emerald-600 dark:text-emerald-400 shrink-0">✓</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Panel: Strategy
// ---------------------------------------------------------------------------

function StrategyPanel({
  strategies,
  total,
  mode,
}: {
  strategies: Strategy[]
  total: number
  mode: string
}) {
  return (
    <Panel title="Strategies" badge={`${total} total`}>
      <ModeBanner mode={mode} />
      {strategies.length === 0 ? (
        <p className="text-xs text-slate-500">No strategies proposed yet.</p>
      ) : (
        <div className="space-y-2">
          {strategies.slice(0, 5).map((s) => (
            <div
              key={s.id}
              className="rounded-lg border border-slate-300 p-3 dark:border-slate-800"
            >
              <div className="mb-1 flex items-start justify-between gap-2">
                <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">{s.description || 'Strategy proposal'}</p>
                <span
                  className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-mono ${
                    s.status === 'approved'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400'
                      : s.status === 'rejected'
                        ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-400'
                        : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400'
                  }`}
                >
                  {s.status ?? 'pending'}
                </span>
              </div>
              <div className="flex gap-3 text-xs font-mono text-slate-500">
                {s.expected_improvement != null && (
                  <span>
                    expected:{' '}
                    <b className="text-emerald-600 dark:text-emerald-400">+{(s.expected_improvement * 100).toFixed(0)}%</b>
                  </span>
                )}
                <span>{fmtTime(s.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Panel: Pipeline Status
// ---------------------------------------------------------------------------

function PipelineStatusPanel({ status }: { status: PipelineStatus | null }) {
  const stages = status?.stages
    ? [
        { name: 'Scoring', key: 'scoring' as const, icon: '⚡' },
        { name: 'Reflection', key: 'reflection' as const, icon: '🔁' },
        { name: 'Strategy', key: 'strategy_proposer' as const, icon: '📈' },
      ]
    : []

  return (
    <Panel title="Pipeline Status">
      {!status ? (
        <p className="text-xs text-slate-500">Loading…</p>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {stages.map(({ name, key, icon }) => {
            const stage = status.stages[key]
            return (
              <div
                key={key}
                className="rounded-lg border border-slate-300 p-3 dark:border-slate-800"
              >
                <div className="mb-1 flex items-center gap-1">
                  <span className="text-sm">{icon}</span>
                  <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{name}</p>
                </div>
                <p className={`text-xs font-mono font-bold ${stageColor(stage.status)}`}>
                  {stage.status.toUpperCase()}
                </p>
                <p className="text-xs font-mono text-slate-500">
                  {stage.jobs_processed} runs
                </p>
                <p className="text-xs text-slate-600">
                  {stage.last_run ? fmtTime(stage.last_run) : 'never'}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Panel: Debug
// ---------------------------------------------------------------------------

function DebugPanel({
  trades,
  reflections,
  pipeline,
}: {
  trades: TradeEvaluation[]
  reflections: Reflection[]
  pipeline: PipelineStatus | null
}) {
  const events = [
    ...trades.slice(0, 5).map((t) => ({
      type: `trade_scored`,
      detail: `${t.symbol ?? '?'} grade=${t.grade} score=${fmtScore(t.overall_score)}`,
      at: t.created_at,
    })),
    ...reflections.slice(0, 3).map((r) => ({
      type: 'reflection_run',
      detail: `analyzed=${r.trades_analyzed} clusters=${r.mistake_clusters?.length ?? 0}`,
      at: r.created_at,
    })),
  ]
    .filter((e) => e.at)
    .sort((a, b) => (a.at! > b.at! ? -1 : 1))
    .slice(0, 10)

  return (
    <Panel title="Debug">
      <div className="space-y-1">
        {events.length === 0 ? (
          <p className="text-xs text-slate-500">No events yet.</p>
        ) : (
          events.map((e, i) => (
            <div key={i} className="flex gap-2 text-xs font-mono">
              <span className="shrink-0 text-slate-500 dark:text-slate-600">{fmtTime(e.at)}</span>
              <span className="text-amber-600 dark:text-amber-400 shrink-0">{e.type}</span>
              <span className="text-slate-500 dark:text-slate-400 truncate">{e.detail}</span>
            </div>
          ))
        )}
      </div>
      {pipeline && (
        <div className="mt-2 flex items-center gap-2 text-xs font-mono text-slate-500">
          <span>mode:</span>
          <span className={pipeline.mode === 'db' ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}>
            {pipeline.mode}
          </span>
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export function LearningDashboard() {
  const [trades, setTrades] = useState<TradeEvaluation[]>([])
  const [tradesTotal, setTradesTotal] = useState(0)
  const [tradesMode, setTradesMode] = useState('memory')
  const [metrics, setMetrics] = useState<LearningMetrics | null>(null)
  const [reflections, setReflections] = useState<Reflection[]>([])
  const [reflectionsMode, setReflectionsMode] = useState('memory')
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [strategiesTotal, setStrategiesTotal] = useState(0)
  const [strategiesMode, setStrategiesMode] = useState('memory')
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)
  const [selectedTrade, setSelectedTrade] = useState<TradeEvaluation | null>(null)
  const [lastRefresh, setLastRefresh] = useState<string>('')
  const [errors, setErrors] = useState<string[]>([])
  const cancelRef = useRef(false)

  const load = useCallback(async () => {
    const errs: string[] = []
    const safe = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
      try {
        return await fn()
      } catch (e) {
        errs.push(e instanceof Error ? e.message : 'fetch_failed')
        return null
      }
    }

    const [t, m, r, s, p] = await Promise.all([
      safe(() => apiFetch<TradesResponse>(API_ENDPOINTS.LEARNING_TRADES + '?limit=50')),
      safe(() => apiFetch<LearningMetrics>(API_ENDPOINTS.LEARNING_METRICS)),
      safe(() => apiFetch<ReflectionsResponse>(API_ENDPOINTS.LEARNING_REFLECTIONS_V2 + '?limit=5')),
      safe(() => apiFetch<StrategiesResponse>(API_ENDPOINTS.LEARNING_STRATEGIES + '?limit=10')),
      safe(() => apiFetch<PipelineStatus>(API_ENDPOINTS.LEARNING_PIPELINE_STATUS)),
    ])

    if (cancelRef.current) return

    if (t) { setTrades(t.trades); setTradesTotal(t.total); setTradesMode(t.mode) }
    if (m) setMetrics(m)
    if (r) { setReflections(r.reflections); setReflectionsMode(r.mode) }
    if (s) { setStrategies(s.strategies); setStrategiesTotal(s.total); setStrategiesMode(s.mode) }
    if (p) setPipeline(p)
    setErrors(errs)
    setLastRefresh(new Date().toLocaleTimeString())
  }, [])

  useEffect(() => {
    cancelRef.current = false
    load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      cancelRef.current = true
      window.clearInterval(id)
    }
  }, [load])

  const latestReflection = reflections[0] ?? null

  return (
    <>
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Learning Pipeline
        </h2>
        <div className="flex items-center gap-3">
          {errors.length > 0 && (
            <span className="text-xs font-mono text-rose-500" title={errors.join(', ')}>
              {errors.length} err{errors.length > 1 ? 's' : ''}
            </span>
          )}
          <span className="text-xs text-slate-400">↻ {lastRefresh || '--'}</span>
        </div>
      </div>

      {/* Grid layout */}
      <div className="space-y-4">
        {/* Row 1: Performance + Pipeline */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <AgentPerformancePanel metrics={metrics} />
          </div>
          <PipelineStatusPanel status={pipeline} />
        </div>

        {/* Row 2: Trade Table */}
        <TradeTablePanel
          trades={trades}
          total={tradesTotal}
          mode={tradesMode}
          onSelect={setSelectedTrade}
        />

        {/* Row 3: Reflection + Strategy */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ReflectionPanel reflection={latestReflection} mode={reflectionsMode} />
          <StrategyPanel strategies={strategies} total={strategiesTotal} mode={strategiesMode} />
        </div>

        {/* Row 4: Debug */}
        <DebugPanel trades={trades} reflections={reflections} pipeline={pipeline} />
      </div>

      {/* Trade Detail Modal */}
      {selectedTrade && (
        <TradeDetailModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
      )}
    </>
  )
}
