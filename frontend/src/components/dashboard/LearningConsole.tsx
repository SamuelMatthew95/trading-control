'use client'

import { cn } from '@/lib/utils'
import { formatPercent, formatTimeAgo, signedUSD, toFiniteNum as toFiniteNumber } from '@/lib/formatters'
import { useCodexStore, type AgentLog, type Proposal, type TradeFeedItem } from '@/stores/useCodexStore'
import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'

function gradeTone(grade: string | null | undefined): string {
  const normalized = String(grade ?? '').toUpperCase()
  if (normalized === 'A' || normalized === 'B') return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300'
  if (normalized === 'C') return 'border-amber-400/30 bg-amber-400/10 text-amber-700 dark:text-amber-300'
  if (normalized === 'D' || normalized === 'F') return 'border-rose-400/30 bg-rose-400/10 text-rose-700 dark:text-rose-300'
  return 'border-slate-300 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400'
}

function proposalTone(status: Proposal['status']): string {
  if (status === 'approved') return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300'
  if (status === 'rejected') return 'border-rose-400/30 bg-rose-400/10 text-rose-700 dark:text-rose-300'
  return 'border-amber-400/30 bg-amber-400/10 text-amber-700 dark:text-amber-300'
}

function actionTone(side: string | null | undefined): string {
  return String(side).toLowerCase() === 'sell'
    ? 'border-rose-400/30 bg-rose-400/10 text-rose-700 dark:text-rose-300'
    : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300'
}

function proposalLabel(proposal: Proposal): string {
  return proposal.content || proposal.strategy_name || proposal.proposal_type.replace(/_/g, ' ')
}

function Kpi({ label, value, tone, note }: { label: string; value: string; tone?: string; note?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className={cn('mt-1 font-mono text-lg font-semibold tabular-nums text-slate-900 dark:text-slate-100', tone)}>{value}</p>
      {note && <p className="mt-1 truncate text-[11px] text-slate-500 dark:text-slate-400">{note}</p>}
    </div>
  )
}

function EmptyRow({ colSpan, message }: { colSpan: number; message: string }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-3 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
        {message}
      </td>
    </tr>
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
  const winRate = performanceSummary?.win_rate ?? (closedTrades.length > 0 ? wins / closedTrades.length : null)
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
      <section className={cardClass}>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className={sectionTitleClass}>Learning Control Plane</p>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">
              This page now shows only live learning evidence that is already in the dashboard store: graded fills, proposal outcomes, and learning-agent activity. Backtest calibration widgets were removed from this operator view.
            </p>
          </div>
          <span className="rounded-full border border-slate-200 dark:border-slate-800 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            Source: live dashboard state
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
          <Kpi label="Graded Trades" value={String(gradedTrades.length)} note={`${closedTrades.length} closed fills`} />
          <Kpi label="Win Rate" value={winRate == null ? '--' : formatPercent(winRate, { signed: true })} tone="text-slate-900 dark:text-slate-100" />
          <Kpi label="Total PnL" value={signedUSD(totalPnl)} tone={totalPnl >= 0 ? 'text-emerald-700 dark:text-emerald-300' : 'text-rose-700 dark:text-rose-300'} />
          <Kpi label="Avg Grade Score" value={formatPercent(avgGradeScore, { decimals: 0 })} />
          <Kpi label="Proposal Queue" value={`${pendingProposals} pending`} note={`${approvedProposals} approved`} />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className={cardClass}>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className={sectionTitleClass}>Graded Trade Outcomes</p>
              <p className={mutedClass}>Recent fills with grades, P&L, and trace links.</p>
            </div>
            {latestGrade && <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">Latest {latestGrade.grade ?? 'NR'}</span>}
          </div>
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
                    <tr key={trade.id} className="text-slate-600 dark:text-slate-300">
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className={cn('rounded border px-2 py-0.5 font-mono text-[10px] uppercase', actionTone(trade.side))}>{trade.side}</span>
                          <span className="font-mono font-semibold text-slate-900 dark:text-slate-100">{trade.symbol || '--'}</span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{trade.qty ?? '--'} units</p>
                      </td>
                      <td className={cn('px-3 py-2 font-mono', (pnl ?? 0) >= 0 ? 'text-emerald-700 dark:text-emerald-300' : 'text-rose-700 dark:text-rose-300')}>
                        {pnl == null ? '--' : signedUSD(pnl)}
                        <span className="ml-2 text-slate-500 dark:text-slate-400">{formatPercent(trade.pnl_percent, { signed: true })}</span>
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn('rounded border px-2 py-1 font-mono text-[10px] uppercase', gradeTone(trade.grade))}>{trade.grade ?? 'NR'}</span>
                      </td>
                      <td className="px-3 py-2 font-mono text-slate-500 dark:text-slate-400">{formatPercent(trade.grade_score, { decimals: 0 })}</td>
                      <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                        filled {trade.filled_at ? formatTimeAgo(trade.filled_at) : '--'} · graded {trade.graded_at ? formatTimeAgo(trade.graded_at) : '--'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {traceId ? (
                          <button type="button" onClick={() => setActiveTraceId(traceId)} className="font-mono text-[11px] text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100">
                            {traceId.slice(0, 12)}…
                          </button>
                        ) : (
                          <span className="text-slate-400 dark:text-slate-600">--</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
                {tradeFeed.length === 0 && <EmptyRow colSpan={6} message="No fills yet. Learning outcomes appear after execution and grading." />}
              </tbody>
            </table>
          </div>
        </div>

        <aside className={cardClass}>
          <p className={sectionTitleClass}>Current Learning State</p>
          <div className="mt-3 space-y-2">
            <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest Grade</p>
              <p className="mt-1 font-mono text-sm text-slate-900 dark:text-slate-100">
                {latestGrade ? `${latestGrade.symbol} ${latestGrade.grade ?? 'NR'} / ${formatPercent(latestGrade.grade_score, { decimals: 0 })}` : 'Waiting for first grade'}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest Proposal</p>
              <p className="mt-1 line-clamp-2 text-sm text-slate-600 dark:text-slate-300">
                {latestProposal ? proposalLabel(latestProposal) : 'No proposal generated yet'}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">What operators should check</p>
              <ul className="mt-2 space-y-1 text-xs text-slate-500 dark:text-slate-400">
                <li>• Are poor grades clustering by symbol or side?</li>
                <li>• Did an approved proposal improve realized grades?</li>
                <li>• Are traces attached to every graded execution?</li>
              </ul>
            </div>
          </div>
        </aside>
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <div className={cardClass}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <p className={sectionTitleClass}>Proposal Outcomes</p>
              <p className={mutedClass}>Strategy changes generated by the learning loop.</p>
            </div>
            <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">{proposals.length} total</span>
          </div>
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
                  <tr key={proposal.id} className="text-slate-600 dark:text-slate-300">
                    <td className="max-w-[340px] px-3 py-2">
                      <p className="line-clamp-2 font-medium text-slate-900 dark:text-slate-100">{proposalLabel(proposal)}</p>
                      <p className="mt-1 font-mono text-[11px] text-slate-400 dark:text-slate-600">{proposal.proposal_type.replace(/_/g, ' ')}</p>
                    </td>
                    <td className="px-3 py-2 font-mono text-slate-500 dark:text-slate-400">{formatPercent(proposal.confidence, { decimals: 0 })}</td>
                    <td className="px-3 py-2 font-mono text-slate-500 dark:text-slate-400">{formatPercent(proposal.grade_score, { decimals: 0 })}</td>
                    <td className="px-3 py-2">
                      <span className={cn('rounded border px-2 py-1 font-mono text-[10px] uppercase', proposalTone(proposal.status))}>{proposal.status}</span>
                    </td>
                  </tr>
                ))}
                {proposals.length === 0 && <EmptyRow colSpan={4} message="No strategy proposals yet. Proposal evidence appears here after reflection." />}
              </tbody>
            </table>
          </div>
        </div>

        <div className={cardClass}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <p className={sectionTitleClass}>Learning Agent Activity</p>
              <p className={mutedClass}>Only grade, reflection, proposal, and learning events.</p>
            </div>
            <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">{learningLogs.length} events</span>
          </div>
          <div className="rounded-lg border border-slate-200 dark:border-slate-800">
            {learningLogs.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-slate-500 dark:text-slate-400">No learning-agent events have streamed yet.</p>
            ) : (
              <div className="divide-y divide-slate-200 dark:divide-slate-800/80">
                {learningLogs.map((log, index) => (
                  <div key={`${log.trace_id ?? log.timestamp}-${index}`} className="grid grid-cols-[120px_1fr] gap-3 px-3 py-2 text-xs">
                    <div>
                      <p className="truncate font-semibold text-slate-600 dark:text-slate-300">{String(log.agent_name ?? log.agent ?? 'Agent')}</p>
                      <p className="font-mono text-[11px] text-slate-400 dark:text-slate-600">{log.timestamp ? formatTimeAgo(log.timestamp) : '--'}</p>
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-slate-500 dark:text-slate-400">{log.event_type ?? 'learning_event'}</p>
                      <p className="mt-1 line-clamp-2 text-slate-500 dark:text-slate-400">{log.message ?? log.primary_edge ?? 'No message provided.'}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
