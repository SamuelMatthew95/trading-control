'use client'

import type { ReactNode } from 'react'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { PROPOSAL_APPROVED, PROPOSAL_PENDING } from '@/constants/trading'
import { Activity, ArrowUpRight, Brain, Gauge, Lightbulb, TrendingDown, TrendingUp, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { formatPercent, formatTimeAgo, signedUSD, toFiniteNum as toFiniteNumber } from '@/lib/formatters'
import { useDashboardStore, type AgentLog, type Proposal, type TradeFeedItem } from '@/stores/useDashboardStore'
import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { pnlColorClass, proposalStatusClass } from '@/lib/dashboard-helpers'
// Reuse the shared learning-grade colour language (the Cognitive page uses the
// same A/B/C/D/F scale) instead of re-deriving hardcoded emerald/rose classes.
import { actionTone } from '@/lib/cognitive'
import { gradeChipClass, gradeTone } from '@/lib/grade-colors'
import { EmptyState } from '@/components/ui/empty-state'
import { Meter } from '@/components/ui/meter'
import { StatTile } from '@/components/ui/stat-tile'

// Decorative icon-chip tints. Neutral uses the muted chrome scale; the rest map
// onto the semantic design tokens so the accents track the app palette.
type Accent = 'brand' | 'success' | 'danger' | 'warning' | 'neutral'

const ACCENT_CHIP: Record<Accent, string> = {
  brand: 'bg-brand/10 text-brand',
  success: 'bg-success/10 text-success',
  danger: 'bg-danger/10 text-danger',
  warning: 'bg-warning/10 text-warning',
  neutral: 'bg-muted text-muted-foreground',
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

function IconChip({ icon: Icon, accent = 'brand' }: { icon: IconType; accent?: Accent }) {
  return (
    <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', ACCENT_CHIP[accent])}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
    </span>
  )
}

function PanelHeader({
  icon,
  accent = 'brand',
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

const tableWrapClass = 'overflow-x-auto rounded-lg border'
const tableHeadRowClass = 'bg-muted/60 text-3xs uppercase tracking-caps text-muted-foreground'
const tableRowClass = 'text-foreground/70 transition-colors hover:bg-muted/40'

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
  const tradeFeed = useDashboardStore((state) => state.tradeFeed)
  const proposals = useDashboardStore((state) => state.proposals)
  const agentLogs = useDashboardStore((state) => state.agentLogs)
  const performanceSummary = useDashboardStore((state) => state.performanceSummary)

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
  const pendingProposals = proposals.filter((proposal) => proposal.status === PROPOSAL_PENDING).length
  const approvedProposals = proposals.filter((proposal) => proposal.status === PROPOSAL_APPROVED).length
  const learningLogs = recentLearningLogs(agentLogs)

  const latestGrade = sortedByTime(gradedTrades)[0]
  const latestProposal = sortedByTime(proposals)[0]

  const statTileClass = 'px-3 py-3 sm:p-3'
  const statValueClass = 'font-mono text-2xl font-semibold tabular-nums'

  return (
    <div className="space-y-3">
      {/* Hero summary band — title + headline KPIs */}
      <section className="rounded-xl border bg-gradient-to-br from-card via-card to-brand/5 p-3 shadow-card dark:from-card/80 dark:via-card/80 dark:to-brand/10 sm:p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand/10 text-brand">
              <Brain className="h-5 w-5" aria-hidden />
            </span>
            <div>
              <p className={sectionTitleClass}>{UI_COPY.learning.title}</p>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
                {UI_COPY.learning.description}
              </p>
            </div>
          </div>
          <span className="rounded-full border px-2 py-1 font-mono text-3xs uppercase tracking-caps text-muted-foreground">
            {UI_COPY.learning.sourceBadge}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile
            label={UI_COPY.learning.statGradedTrades}
            value={String(gradedTrades.length)}
            lines={[`of ${closedTrades.length} closed fills`]}
            icon={<IconChip icon={Activity} accent="brand" />}
            valueClassName={statValueClass}
            className={statTileClass}
          />
          <StatTile
            label={UI_COPY.learning.statWinRate}
            value={winRate == null ? NO_DATA : formatPercent(winRate, { signed: true })}
            lines={[`${wins}W · ${losses}L`]}
            icon={<IconChip icon={TrendingUp} accent="success" />}
            valueClassName={statValueClass}
            className={statTileClass}
          />
          <StatTile
            label={UI_COPY.learning.statTotalPnl}
            value={signedUSD(totalPnl)}
            lines={[' ']}
            icon={<IconChip icon={totalPnl >= 0 ? TrendingUp : TrendingDown} accent={totalPnl >= 0 ? 'success' : 'danger'} />}
            valueClassName={cn(statValueClass, pnlColorClass(totalPnl))}
            className={statTileClass}
          />
          <StatTile
            label={UI_COPY.learning.statAvgGradeScore}
            value={formatPercent(avgGradeScore, { decimals: 0 })}
            lines={[`${gradedTrades.length} ${UI_COPY.learning.graded}`]}
            icon={<IconChip icon={Gauge} accent="brand" />}
            valueClassName={statValueClass}
            className={statTileClass}
          />
          <StatTile
            label={UI_COPY.learning.statProposalQueue}
            value={`${pendingProposals} ${UI_COPY.learning.pending}`}
            lines={[`${approvedProposals} ${UI_COPY.learning.approved}`]}
            icon={<IconChip icon={Lightbulb} accent="warning" />}
            valueClassName={statValueClass}
            className={statTileClass}
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
              accent="brand"
              title={UI_COPY.learning.gradedOutcomesTitle}
              subtitle={UI_COPY.learning.gradedOutcomesSubtitle}
              right={
                latestGrade ? (
                  <span className={cn(gradeChipClass, gradeTone(latestGrade.grade))}>
                    {UI_COPY.learning.latest} {latestGrade.grade ?? UI_COPY.learning.notRated}
                  </span>
                ) : undefined
              }
            />
            {tradeFeed.length === 0 ? (
              <EmptyState icon={Activity} message={UI_COPY.empty.learningOutcomes} />
            ) : (
              <div className={tableWrapClass}>
                <table className="w-full min-w-[760px] text-left text-xs">
                  <thead className={tableHeadRowClass}>
                    <tr>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.trade}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.pnl}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.grade}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.score}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.lifecycle}</th>
                      <th className="px-3 py-2 text-right font-semibold">{UI_COPY.learning.columns.trace}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y bg-card dark:bg-card/50">
                    {sortedByTime(tradeFeed).slice(0, 12).map((trade: TradeFeedItem) => {
                      const pnl = toFiniteNumber(trade.pnl)
                      const traceId = trade.execution_trace_id ?? trade.signal_trace_id
                      return (
                        <tr key={trade.id} className={tableRowClass}>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span className={cn(gradeChipClass, actionTone(trade.side))}>{trade.side}</span>
                              <span className="font-mono font-semibold text-foreground">{trade.symbol || NO_DATA}</span>
                            </div>
                            <p className="mt-1 text-2xs text-muted-foreground">
                              {trade.qty ?? NO_DATA} {UI_COPY.learning.units}
                            </p>
                          </td>
                          <td className={cn('px-3 py-2 font-mono', pnlColorClass(pnl ?? 0))}>
                            {pnl == null ? NO_DATA : signedUSD(pnl)}
                            <span className="ml-2 text-muted-foreground">{formatPercent(trade.pnl_percent, { signed: true })}</span>
                          </td>
                          <td className="px-3 py-2">
                            <span className={cn(gradeChipClass, gradeTone(trade.grade))}>{trade.grade ?? UI_COPY.learning.notRated}</span>
                          </td>
                          <td className="px-3 py-2">
                            <span className="font-mono text-muted-foreground">{formatPercent(trade.grade_score, { decimals: 0 })}</span>
                            {toPct(trade.grade_score) != null ? (
                              <div className="mt-1.5 w-16">
                                <Meter value={toPct(trade.grade_score) ?? 0} label={UI_COPY.learning.columns.score} />
                              </div>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">
                            {UI_COPY.learning.filled} {trade.filled_at ? formatTimeAgo(trade.filled_at) : NO_DATA} · {UI_COPY.learning.graded}{' '}
                            {trade.graded_at ? formatTimeAgo(trade.graded_at) : NO_DATA}
                          </td>
                          <td className="px-3 py-2 text-right">
                            {traceId ? (
                              <button
                                type="button"
                                onClick={() => setActiveTraceId(traceId)}
                                className="inline-flex items-center gap-1 font-mono text-2xs text-muted-foreground transition-colors hover:text-brand"
                              >
                                {traceId.slice(0, 10)}…
                                <ArrowUpRight className="h-3 w-3" aria-hidden />
                              </button>
                            ) : (
                              <span className="text-muted-foreground/60">{NO_DATA}</span>
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
              title={UI_COPY.learning.proposalOutcomesTitle}
              subtitle={UI_COPY.learning.proposalOutcomesSubtitle}
              right={
                <span className="font-mono text-2xs text-muted-foreground">
                  {proposals.length} {UI_COPY.learning.total}
                </span>
              }
            />
            {proposals.length === 0 ? (
              <EmptyState icon={Lightbulb} message={UI_COPY.empty.proposals} />
            ) : (
              <div className={tableWrapClass}>
                <table className="w-full min-w-[680px] text-left text-xs">
                  <thead className={tableHeadRowClass}>
                    <tr>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.change}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.expected}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.gradeDelta}</th>
                      <th className="px-3 py-2 font-semibold">{UI_COPY.learning.columns.status}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y bg-card dark:bg-card/50">
                    {sortedByTime(proposals).slice(0, 8).map((proposal) => (
                      <tr key={proposal.id} className={tableRowClass}>
                        <td className="max-w-[340px] px-3 py-2">
                          <p className="line-clamp-2 font-medium text-foreground" title={proposalLabel(proposal)}>{proposalLabel(proposal)}</p>
                          <p className="mt-1 font-mono text-2xs text-muted-foreground/70">{proposal.proposal_type.replace(/_/g, ' ')}</p>
                        </td>
                        <td className="px-3 py-2 font-mono text-muted-foreground">{formatPercent(proposal.confidence, { decimals: 0 })}</td>
                        <td className="px-3 py-2 font-mono text-muted-foreground">{formatPercent(proposal.grade_score, { decimals: 0 })}</td>
                        <td className="px-3 py-2">
                          <span className={cn(gradeChipClass, 'border-transparent', proposalStatusClass(proposal.status))}>{proposal.status}</span>
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
            <PanelHeader icon={Gauge} accent="brand" title={UI_COPY.learning.currentStateTitle} />
            <div className="space-y-2">
              <div className="rounded-lg border bg-card px-3 py-2.5 dark:bg-card/70">
                <p className="text-3xs uppercase tracking-caps text-muted-foreground">{UI_COPY.learning.latestGrade}</p>
                {latestGrade ? (
                  <>
                    <div className="mt-1.5 flex items-center gap-2">
                      <span className={cn(gradeChipClass, 'text-xs', gradeTone(latestGrade.grade))}>
                        {latestGrade.grade ?? UI_COPY.learning.notRated}
                      </span>
                      <span className="font-mono text-sm font-semibold text-foreground">{latestGrade.symbol}</span>
                      <span className="ml-auto font-mono text-xs text-muted-foreground">{formatPercent(latestGrade.grade_score, { decimals: 0 })}</span>
                    </div>
                    <Meter value={toPct(latestGrade.grade_score) ?? 0} label={UI_COPY.learning.latestGrade} className="mt-2" />
                  </>
                ) : (
                  <p className="mt-1.5 font-mono text-sm text-muted-foreground/70">{NO_DATA}</p>
                )}
              </div>
              <div className="rounded-lg border bg-card px-3 py-2.5 dark:bg-card/70">
                <p className="text-3xs uppercase tracking-caps text-muted-foreground">{UI_COPY.learning.latestProposal}</p>
                <div className="mt-1.5 flex items-start gap-2">
                  <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                  <p
                    className="line-clamp-2 text-sm text-foreground/70"
                    title={latestProposal ? proposalLabel(latestProposal) : undefined}
                  >
                    {latestProposal ? proposalLabel(latestProposal) : UI_COPY.learning.noProposalYet}
                  </p>
                </div>
              </div>
            </div>
          </aside>

          <aside className={cardClass}>
            <PanelHeader
              icon={Activity}
              accent="brand"
              title={UI_COPY.learning.activityTitle}
              subtitle={UI_COPY.learning.activitySubtitle}
              right={
                <span className="font-mono text-2xs text-muted-foreground">
                  {learningLogs.length} {UI_COPY.learning.events}
                </span>
              }
            />
            {learningLogs.length === 0 ? (
              <EmptyState icon={Activity} message={UI_COPY.empty.learningEvents} />
            ) : (
              <div className="divide-y">
                {learningLogs.map((log, index) => (
                  <div key={`${log.trace_id ?? log.timestamp}-${index}`} className="flex gap-3 px-1 py-2.5 text-xs">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand/60" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate font-semibold text-foreground/80" title={String(log.agent_name ?? log.agent ?? 'Agent')}>
                          {String(log.agent_name ?? log.agent ?? 'Agent')}
                        </p>
                        <span className="shrink-0 font-mono text-3xs text-muted-foreground/70">{log.timestamp ? formatTimeAgo(log.timestamp) : NO_DATA}</span>
                      </div>
                      <span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-3xs text-muted-foreground">
                        {log.event_type ?? 'learning_event'}
                      </span>
                      <p className="mt-1 line-clamp-2 text-muted-foreground" title={log.message ?? log.primary_edge ?? undefined}>
                        {log.message ?? log.primary_edge ?? UI_COPY.learning.noMessage}
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
