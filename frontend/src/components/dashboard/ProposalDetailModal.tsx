'use client'

import { formatPercent } from '@/lib/formatters'
import { proposalStatusClass } from '@/lib/dashboard-helpers'
import { sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { proposalRouting } from '@/lib/proposal-routing'
import { cn } from '@/lib/utils'
import type { Proposal } from '@/stores/useDashboardStore'

/**
 * Proposal drill-in — the full candidate change, what happens on approve, the
 * backtest evidence, and traceability. Reads the proposal already in the store
 * (no fetch), so "click → view → learn" works in DB and memory mode alike.
 */
export function ProposalDetailModal({
  proposal,
  onClose,
}: {
  proposal: Proposal
  onClose: () => void
}) {
  const routing = proposalRouting(proposal.proposal_type)
  const content =
    proposal.content || proposal.strategy_name || proposal.proposal_type.replace(/_/g, ' ')

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
            <p className={sectionTitleClass}>Proposal · {proposal.proposal_type.replace(/_/g, ' ')}</p>
            <p className={cn(mutedClass, 'font-mono')}>ID {proposal.id}</p>
          </div>
          <span
            className={cn(
              'rounded border px-2 py-0.5 font-mono text-[10px] uppercase',
              proposalStatusClass(proposal.status),
            )}
          >
            {proposal.status}
          </span>
        </div>

        {/* What it is */}
        <Section label="Candidate change">
          <p className="whitespace-pre-wrap text-sm text-slate-800 dark:text-slate-200">{content}</p>
        </Section>

        {/* What happens on approve — plain English */}
        <Section label="On approve">
          <p className="text-sm text-slate-700 dark:text-slate-300">{routing.hint}</p>
          <p className={cn(mutedClass, 'mt-1')}>routes to: {routing.label}</p>
        </Section>

        {/* Evidence */}
        <Section label="Evidence">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Metric label="confidence" value={formatPercent(proposal.confidence)} />
            <Metric
              label="backtest delta"
              value={proposal.grade_score != null ? formatPercent(proposal.grade_score) : '--'}
            />
            <Metric label="requires approval" value={proposal.requires_approval ? 'yes' : 'no'} />
          </div>
        </Section>

        {/* Provenance */}
        <Section label="Traceability">
          <dl className="grid grid-cols-1 gap-1 font-mono text-[11px] text-slate-500 dark:text-slate-400">
            <Row k="trace_id" v={proposal.trace_id} />
            <Row k="reflection_trace_id" v={proposal.reflection_trace_id} />
            <Row k="source" v={proposal.source} />
            <Row k="symbol" v={proposal.symbol} />
            <Row k="created_at" v={proposal.created_at ?? proposal.timestamp} />
          </dl>
        </Section>
      </div>
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {label}
      </p>
      {children}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 p-2 text-center dark:border-slate-800">
      <p className="font-mono text-sm tabular-nums text-slate-900 dark:text-slate-100">{value}</p>
      <p className={mutedClass}>{label}</p>
    </div>
  )
}

function Row({ k, v }: { k: string; v?: string | null }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0">{k}</dt>
      <dd className="truncate text-slate-600 dark:text-slate-300">{v || '--'}</dd>
    </div>
  )
}
