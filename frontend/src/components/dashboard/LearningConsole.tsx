'use client'

import type { ReactNode } from 'react'
import { Activity, ArrowUpRight, Brain, Gauge, Lightbulb, TrendingDown, TrendingUp, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { formatPercent, formatTimeAgo, signedUSD, toFiniteNum as toFiniteNumber } from '@/lib/formatters'
import { useCodexStore, type AgentLog, type Proposal, type TradeFeedItem } from '@/stores/useCodexStore'
import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { pnlColorClass, proposalStatusClass } from '@/lib/dashboard-helpers'
// Reuse the shared learning-grade colour language (the Cognitive page uses the
// same A/B/C/D/F scale) instead of re-deriving hardcoded emerald/rose classes.
import { actionTone, gradeTone } from '@/lib/cognitive'
import { EmptyState } from '@/components/ui/empty-state'

// Decorative icon-chip tints. Neutral uses the slate chrome scale; the rest map
// onto the semantic design tokens so the accents track the app palette.
type Accent = 'primary' | 'success' | 'danger' | 'warning' | 'neutral'

const ACCENT_CHIP: Record<Accent, string> = {
  primary: 'bg-primary/10 text-primary',
  success: 'bg-success/10 text-success',
  danger: 'bg-danger/10 text-danger',
  warning: 'bg-warning/10 text-warning',
  neutral: 'bg-slate-100 text-slate-500 dark:bg-slate-800/60 dark:text-slate-400',
}

// Icons are decorative throughout this view (every one sits beside a text
// label) and are rendered with `aria-hidden` to keep them out of the
// accessibility tree. LucideIcon is the shared icon-component type.
type IconType = LucideIcon

function proposalLabel(proposal: Proposal): string {
  return proposal.content || proposal.strategy_name || proposal.proposal_type.replace(/_/g, ' ')
}

/** Coerce a grade score (ratio 0–1 or already a percent) to a 0–100 scale. */
function toPct(value: unknown): number | null {
  const n = toFiniteNumber(value)
  if (n == null) return null
  return Math.abs(n) <= 1 ? n * 100 : n
}

function IconChip({ icon: Icon, accent = 'primary' }: { icon: IconType; accent?: Accent }) {
  return (
    <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', ACCENT_CHIP[accent])}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
    </span>
  )
}

function PanelHeader({
  icon,
  accent = 'primary',
  title,
  subtitle,
  right,
}: {
  icon: IconType
  accent?: Accent
  title: string
  subtitle?: string
  right?: ReactNode
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <IconChip icon={icon} accent={accent} />
        <div>
          <p className={sectionTitleClass}>{title}</p>
          {subtitle ? <p className={mutedClass}>{subtitle}</p> : null}
        </div>
      </div>
      {right}
    </div>
  )
}

function StatTile({
  label,
  value,
  note,
  icon,
  accent = 'neutral',
  valueTone,
}: {
  label: string
  value: string
  note?: string
  icon: IconType
  accent?: Accent
  valueTone?: string
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 transition-colors hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950/70 dark:hover:border-slate-700">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
        <IconChip icon={icon} accent={accent} />
      </div>
      <p className={cn('mt-2 font-mono text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100', valueTone)}>{value}</p>
      <p className="mt-0.5 truncate text-[11px] text-slate-500 dark:text-slate-400">{note ?? '\u00A0'}</p>
    </div>
  )
}

function Meter({ value, className }: { value: number | null; className?: string }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value))
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800', className)}>
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
    </div>
  )
}

function sortedByTime<T extends { created_at?: string | null; filled_at?: string | null; graded_at?: string | null; timestamp?: string | null }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const aTime = new Date(a.graded_at ?? a.filled_at ?? a.created_at ?? a.timestamp ?? 0).getTime()
    const bTime = new Date(b.graded_at ?? b.filled_at ?? b.created_at ?? b.timestamp ?? 0).getTime()
    return (Number.isFinite(bTime) ? bTime : 0) - (Number.isFinite(aTime) ? aTime : 0)
  })
}

function recentLearningLogs(logs: AgentLog[]): AgentLog[] {
  return logs
    .filter((log) => {
      const haystack = `${log.agent_name ?? log.agent ?? ''} ${log.event_type ?? ''} ${log.message ?? ''}`.toLowerCase()
      return haystack.includes('grade') || haystack.includes('reflection') || haystack.includes('proposal') || haystack.includes('learn')
    })
    .slice(0, 8)
}

export function LearningConsole({ setActiveTraceId }: { setActiveTraceId: (id: string | null) => void }) {
  const tradeFeed = useCodexStore((state) => state.tradeFeed)
  const proposals = useCodexStore((state) => state.proposals)
  const agentLogs = useCodexStore((state) => state.agentLogs)
  const performanceSummary = useCodexStore((state) => state.performanceSummary)

  const gradedTrades = tradeFeed.filter((trade) => trade.grade || trade.grade_score != null)
  const closedTrades = tradeFeed.filter((trade) => trade.pnl != null)
  const totalPnl = performanceSummary?.total_pnl ?? closedTrades.reduce((sum, trade) => sum + (toFiniteNumber(trade.pnl) ?? 0), 0)
  const wins = closedTrades.filter((trade) => (toFiniteNumber(trade.pnl) ?? 0) > 0).length
  const losses = closedTrades.filter((trade) => (toFiniteNumber(trade.pnl) ?? 0) < 0).length
  // Fallback win rate excludes scratch trades (pnl == 0) from the denominator to
  // match the backend canonical definition: winning / (winning + losing).
  const decidedTrades = wins + losses
  const winRate = performanceSummary?.win_rate ?? (decidedTrades > 0 ? wins / decidedTrades : null)
  const avgGradeScore = gradedTrades.length > 0
    ? gradedTrades.reduce((sum, trade) => sum + (toFiniteNumber(trade.grade_score) ?? 0), 0) / gradedTrades.length
    : null
  const pendingProposals = proposals.filter((proposal) => proposal.status === 'pending').length
  const approvedProposals = proposals.filter((proposal) => proposal.status === 'approved').length
  const learningLogs = recentLearningLogs(agentLogs)

  const latestGrade = sortedByTime(gradedTrades)[0]
  const latestProposal = sortedByTime(proposals)[0]

  return (
    <div className="space-y-3">
      {/* Hero summary band — title + headline KPIs */}
      <section className="rounded-xl border border-slate-200 bg-gradient-to-br from-white via-white to-primary/5 p-3 shadow-sm shadow-slate-900/5 dark:border-slate-800/80 dark:from-slate-950/80 dark:via-slate-950/80 dark:to-primary/10 dark:shadow-black/20 sm:p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Brain className="h-5 w-5" aria-hidden />
            </span>
            <div>
              <p className={sectionTitleClass}>Learning Control Plane</p>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">
                Live learning evidence from the dashboard store — graded fills, proposal outcomes, and learning-agent activity.
              </p>
            </div>
          </div>
          <span className="rounded-full border border-slate-200 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:text-slate-400">
            Source: live dashboard state
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile
            label="Graded Trades"
            value={String(gradedTrades.length)}
            note={`of ${closedTrades.length} closed fills`}
            icon={Activity}
            accent="primary"
          />
          <StatTile
            label="Win Rate"
            value={winRate == null ? '--' : formatPercent(winRate, { signed: true })}
            note={`${wins}W · ${losses}L`}
            icon={TrendingUp}
            accent="success"
          />
          <StatTile
            label="Total PnL"
            value={signedUSD(totalPnl)}
            icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
            accent={totalPnl >= 0 ? 'success' : 'danger'}
            valueTone={pnlColorClass(totalPnl)}
          />
          <StatTile
            label="Avg Grade Score"
            value={formatPercent(avgGradeScore, { decimals: 0 })}
            note={`${gradedTrades.length} graded`}
            icon={Gauge}
            accent="primary"
          />
          <StatTile
            label="Proposal Queue"
            value={`${pendingProposals} pending`}
            note={`${approvedProposals} approved`}
            icon={Lightbulb}
            accent="warning"
          />
        </div>
      </section>

      {/* Main grid — evidence tables (left) + at-a-glance rail (right) */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-3">
          {/* Graded Trade Outcomes */}
          <section className={cardClass}>
            <PanelHeader
              icon={Activity}
              accent="primary"
              title="Graded Trade Outcomes"
              subtitle="Recent fills with grades, P&L, and trace links."
              right={
                latestGrade ? (
                  <span className={cn('rounded border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase', gradeTone(latestGrade.grade))}>
                    Latest {latestGrade.grade ?? 'NR'}
                  </span>
                ) : undefined
              }
            />
            {tradeFeed.length === 0 ? (
              <EmptyState icon={Activity} message="No fills yet — learning outcomes appear after execution and grading." />
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
                <table className="w-full min-w-[760px] text-left text-xs">
                  <thead className="bg-slate-100 dark:bg-slate-900/80 text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Trade</th>
                      <th className="px-3 py-2 font-semibold">P&L</th>
                      <th className="px-3 py-2 font-semibold">Grade</th>
                      <th className="px-3 py-2 font-semibold">Score</th>
                      <th className="px-3 py-2 font-semibold">Lifecycle</th>
                      <th className="px-3 py-2 text-right font-semibold">Trace</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800/80 bg-white dark:bg-slate-950/50">
                    {sortedByTime(tradeFeed).slice(0, 12).map((trade: TradeFeedItem) => {
                      const pnl = toFiniteNumber(trade.pnl)
                      const traceId = trade.execution_trace_id ?? trade.signal_trace_id
                      return (
                        <tr key={trade.id} className="text-slate-600 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-900/40">
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span className={cn('rounded border px-2 py-0.5 font-mono text-[10px] uppercase', actionTone(trade.side))}>{trade.side}</span>
                              <span className="font-mono font-semibold text-slate-900 dark:text-slate-100">{trade.symbol || '--'}</span>
                            </div>
                            <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{trade.qty ?? '--'} units</p>
                          </td>
                          <td className={cn('px-3 py-2 font-mono', pnlColorClass(pnl ?? 0))}>
                            {pnl == null ? '--' : signedUSD(pnl)}
                            <span className="ml-2 text-slate-500 dark:text-slate-400">{formatPercent(trade.pnl_percent, { signed: true })}</span>
                          </td>
                          <td className="px-3 py-2">
                            <span className={cn('rounded border px-2 py-1 font-mono text-[10px] uppercase', gradeTone(trade.grade))}>{trade.grade ?? 'NR'}</span>
                          </td>
                          <td className="px-3 py-2">
                            <span className="font-mono text-slate-500 dark:text-slate-400">{formatPercent(trade.grade_score, { decimals: 0 })}</span>
                            {toPct(trade.grade_score) != null ? (
                              <div className="mt-1.5 w-16">
                                <Meter value={toPct(trade.grade_score)} />
                              </div>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                            filled {trade.filled_at ? formatTimeAgo(trade.filled_at) : '--'} · graded {trade.graded_at ? formatTimeAgo(trade.graded_at) : '--'}
                          </td>
                          <td className="px-3 py-2 text-right">
                            {traceId ? (
                              <button
                                type="button"
                                onClick={() => setActiveTraceId(traceId)}
                                className="inline-flex items-center gap-1 font-mono text-[11px] text-slate-500 transition-colors hover:text-primary dark:text-slate-400 dark:hover:text-primary"
                              >
                                {traceId.slice(0, 10)}…
                                <ArrowUpRight className="h-3 w-3" aria-hidden />
                              </button>
                            ) : (
                              <span className="text-slate-400 dark:text-slate-600">--</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Proposal Outcomes */}
          <section className={cardClass}>
            <PanelHeader
              icon={Lightbulb}
              accent="warning"
              title="Proposal Outcomes"
              subtitle="Strategy changes generated by the learning loop."
              right={<span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">{proposals.length} total</span>}
            />
            {proposals.length === 0 ? (
              <EmptyState icon={Lightbulb} message="No strategy proposals yet — evidence appears here after reflection." />
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
                <table className="w-full min-w-[680px] text-left text-xs">
                  <thead className="bg-slate-100 dark:bg-slate-900/80 text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Change</th>
                      <th className="px-3 py-2 font-semibold">Expected</th>
                      <th className="px-3 py-2 font-semibold">Grade Δ</th>
                      <th className="px-3 py-2 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800/80 bg-white dark:bg-slate-950/50">
                    {sortedByTime(proposals).slice(0, 8).map((proposal) => (
                      <tr key={proposal.id} className="text-slate-600 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-900/40">
                        <td className="max-w-[340px] px-3 py-2">
                          <p className="line-clamp-2 font-medium text-slate-900 dark:text-slate-100" title={proposalLabel(proposal)}>{proposalLabel(proposal)}</p>
                          <p className="mt-1 font-mono text-[11px] text-slate-400 dark:text-slate-600">{proposal.proposal_type.replace(/_/g, ' ')}</p>
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-500 dark:text-slate-400">{formatPercent(proposal.confidence, { decimals: 0 })}</td>
                        <td className="px-3 py-2 font-mono text-slate-500 dark:text-slate-400">{formatPercent(proposal.grade_score, { decimals: 0 })}</td>
                        <td className="px-3 py-2">
                          <span className={cn('rounded border px-2 py-1 font-mono text-[10px] uppercase', proposalStatusClass(proposal.status))}>{proposal.status}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        {/* At-a-glance rail */}
        <div className="space-y-3">
          <aside className={cardClass}>
            <PanelHeader icon={Gauge} accent="primary" title="Current Learning State" />
            <div className="space-y-2">
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 dark:border-slate-800 dark:bg-slate-950/70">
                <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest Grade</p>
                {latestGrade ? (
                  <>
                    <div className="mt-1.5 flex items-center gap-2">
                      <span className={cn('rounded border px-2 py-0.5 font-mono text-xs font-semibold uppercase', gradeTone(latestGrade.grade))}>
                        {latestGrade.grade ?? 'NR'}
                      </span>
                      <span className="font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">{latestGrade.symbol}</span>
                      <span className="ml-auto font-mono text-xs text-slate-500 dark:text-slate-400">{formatPercent(latestGrade.grade_score, { decimals: 0 })}</span>
                    </div>
                    <Meter value={toPct(latestGrade.grade_score)} className="mt-2" />
                  </>
                ) : (
                  <p className="mt-1 text-sm text-slate-400 dark:text-slate-500">Waiting for first grade</p>
                )}
              </div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 dark:border-slate-800 dark:bg-slate-950/70">
                <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest Proposal</p>
                <div className="mt-1.5 flex items-start gap-2">
                  <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                  <p
                    className="line-clamp-2 text-sm text-slate-600 dark:text-slate-300"
                    title={latestProposal ? proposalLabel(latestProposal) : undefined}
                  >
                    {latestProposal ? proposalLabel(latestProposal) : 'No proposal generated yet'}
                  </p>
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 dark:border-slate-800 dark:bg-slate-950/70">
                <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">What operators should check</p>
                <ul className="mt-2 space-y-1.5 text-xs text-slate-500 dark:text-slate-400">
                  {[
                    'Are poor grades clustering by symbol or side?',
                    'Did an approved proposal improve realized grades?',
                    'Are traces attached to every graded execution?',
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/50" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </aside>

          <aside className={cardClass}>
            <PanelHeader
              icon={Activity}
              accent="primary"
              title="Learning Agent Activity"
              subtitle="Grade, reflection, proposal, and learning events."
              right={<span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">{learningLogs.length} events</span>}
            />
            {learningLogs.length === 0 ? (
              <EmptyState icon={Activity} message="No learning-agent events have streamed yet." />
            ) : (
              <div className="divide-y divide-slate-200 dark:divide-slate-800/80">
                {learningLogs.map((log, index) => (
                  <div key={`${log.trace_id ?? log.timestamp}-${index}`} className="flex gap-3 px-1 py-2.5 text-xs">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary/60" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate font-semibold text-slate-700 dark:text-slate-200" title={String(log.agent_name ?? log.agent ?? 'Agent')}>
                          {String(log.agent_name ?? log.agent ?? 'Agent')}
                        </p>
                        <span className="shrink-0 font-mono text-[10px] text-slate-400 dark:text-slate-500">{log.timestamp ? formatTimeAgo(log.timestamp) : '--'}</span>
                      </div>
                      <span className="mt-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
                        {log.event_type ?? 'learning_event'}
                      </span>
                      <p className="mt-1 line-clamp-2 text-slate-500 dark:text-slate-400" title={log.message ?? log.primary_edge ?? undefined}>
                        {log.message ?? log.primary_edge ?? 'No message provided.'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
